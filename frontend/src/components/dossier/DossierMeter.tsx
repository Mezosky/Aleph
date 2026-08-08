import { useId, useState } from 'react'
import ActorPopover from '@/components/dossier/ActorPopover'
import { dataUrl } from '@/lib/data'
import type { ActorProfile, DossierMeter as Meter } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

const CONFIDENCE = { low: 'baja', medium: 'media', high: 'alta' } as const

function PolePreview({ actors, side }: { actors: ActorProfile[]; side: 'left' | 'right' }) {
  const visible = actors.slice(0, 2)
  const remaining = actors.length - visible.length

  return (
    <span className={`flex -space-x-2 ${side === 'right' ? 'justify-end' : ''}`} aria-hidden="true">
      {visible.map((actor) => (
        <img
          key={actor.id}
          src={dataUrl(actor.image)}
          alt=""
          className="h-11 w-11 rounded-full border-2 border-surface-card bg-surface-raised object-cover object-top grayscale transition group-hover/actors:grayscale-0 group-focus-visible/actors:grayscale-0"
          loading="lazy"
        />
      ))}
      {remaining > 0 && (
        <span className="relative flex h-11 w-11 items-center justify-center rounded-full border-2 border-surface-card bg-surface-raised text-caption font-semibold tabular text-ink-primary">
          +{remaining}
        </span>
      )}
    </span>
  )
}

function ActorBubbleGroup({
  actors,
  align,
}: {
  actors: ActorProfile[]
  align: 'left' | 'right'
}) {
  return (
    <span className={`flex flex-wrap gap-1.5 ${align === 'right' ? 'justify-end' : ''}`}>
      {actors.map((actor) => (
        <ActorPopover key={actor.id} actor={actor} trigger="avatar" align={align} />
      ))}
    </span>
  )
}

export default function DossierMeter({ meter, actors = [] }: { meter: Meter; actors?: ActorProfile[] }) {
  const { language, tr } = useLanguage()
  const [actorsExpanded, setActorsExpanded] = useState(false)
  const actorsPanelId = `meter-actors-${useId().replaceAll(':', '')}`
  const bounded = Math.max(0, Math.min(100, meter.value))
  const byId = new Map(actors.map((actor) => [actor.id, actor]))
  const meterActors = meter.actor_ids.map((id) => byId.get(id)).filter(Boolean) as ActorProfile[]
  const leftActors = meter.pole_actor_ids.left.map((id) => byId.get(id)).filter(Boolean) as ActorProfile[]
  const rightActors = meter.pole_actor_ids.right.map((id) => byId.get(id)).filter(Boolean) as ActorProfile[]
  const poleIds = new Set([...meter.pole_actor_ids.left, ...meter.pole_actor_ids.right])
  const contextualActors = meterActors.filter((actor) => !poleIds.has(actor.id))

  return (
    <article className="border border-line-hairline bg-surface-card p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-micro font-semibold uppercase tracking-[0.16em] text-ink-muted">
            {meter.kind === 'editorial_tone'
              ? tr('Lectura de cobertura', 'Coverage reading')
              : meter.kind === 'public_interest'
                ? tr('Interés público', 'Public interest')
                : tr('Tensión de diseño', 'Design tension')}
          </p>
          <h3 className="mt-2 text-lede font-semibold text-ink-primary">{meter.title}</h3>
        </div>
        <span className="border border-line-hairline bg-surface-sunken px-2 py-1 text-micro uppercase text-ink-secondary">
          {tr('confianza', 'confidence')}{' '}
          {language === 'es'
            ? CONFIDENCE[meter.confidence]
            : { low: 'low', medium: 'medium', high: 'high' }[meter.confidence]}
        </span>
      </div>

      <p className="mt-3 text-caption text-ink-secondary">{meter.question}</p>

      <div className="mt-6">
        {actorsExpanded ? (
          <div
            id={actorsPanelId}
            className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3 border-y border-line-hairline py-3"
          >
            <ActorBubbleGroup actors={leftActors} align="left" />
            <div className="flex max-w-24 flex-col items-center gap-2">
              {contextualActors.length > 0 && <ActorBubbleGroup actors={contextualActors} align="left" />}
              <button
                type="button"
                className="text-micro font-semibold uppercase tracking-wide text-ink-muted underline decoration-line-strong underline-offset-4 hover:text-ink-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                aria-expanded="true"
                aria-controls={actorsPanelId}
                onClick={() => setActorsExpanded(false)}
              >
                {tr('Cerrar', 'Close')}
              </button>
            </div>
            <ActorBubbleGroup actors={rightActors} align="right" />
          </div>
        ) : (
          <button
            type="button"
            className="group/actors mb-2 grid w-full grid-cols-[1fr_auto_1fr] items-end gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            aria-expanded="false"
            aria-controls={actorsPanelId}
            onClick={() => setActorsExpanded(true)}
          >
            <PolePreview actors={leftActors} side="left" />
            <span className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-muted group-hover/actors:text-ink-primary">
              {tr('Ver actores', 'View actors')} · {meterActors.length}
            </span>
            <PolePreview actors={rightActors} side="right" />
          </button>
        )}
        <div
          role="img"
          aria-label={`${meter.title}: ${bounded} ${tr('de', 'out of')} 100, ${tr('desde', 'from')} ${meter.left_label} ${tr('hacia', 'toward')} ${meter.right_label}`}
        >
          <div className="relative h-3 rounded-full bg-[linear-gradient(90deg,var(--div-neg-3),var(--div-mid)_50%,var(--div-pos-3))] shadow-[inset_0_0_0_1px_var(--line-strong)]">
            <span className="absolute left-1/2 top-0 h-full w-px bg-line-strong" aria-hidden="true" />
            <span
              className="absolute top-1/2 h-7 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm border-2 border-ink-primary bg-surface-raised shadow-sm"
              style={{ left: `${bounded}%` }}
              aria-hidden="true"
            />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-micro text-ink-muted">
            <span>{meter.left_label}</span>
            <span className="text-center">{meter.center_label}</span>
            <span className="text-right">{meter.right_label}</span>
          </div>
        </div>
      </div>

      <p className="mt-5 text-body text-ink-primary">{meter.explanation}</p>
      <details className="mt-4 border-t border-line-hairline pt-3">
        <summary className="cursor-pointer text-caption font-semibold text-ink-secondary">
          {tr('Ver cálculo y componentes', 'View calculation and components')}
        </summary>
        <p className="mt-3 text-caption text-ink-secondary">{meter.methodology}</p>
        <ul className="mt-3 space-y-2">
          {meter.evidence.map((item) => (
            <li key={item.label} className="flex items-baseline justify-between gap-4 text-caption">
              <span className="text-ink-secondary">{item.label}</span>
              <span className="tabular font-semibold text-ink-primary">{item.value}</span>
            </li>
          ))}
        </ul>
      </details>
    </article>
  )
}

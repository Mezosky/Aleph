import { useId } from 'react'
import { dataUrl } from '@/lib/data'
import type { ActorProfile } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

const LEGAL_STATUS_ES = {
  investigation_reported: 'investigación informada',
  formally_investigated: 'investigación formalizada',
  charged: 'acusación presentada',
  trial_ongoing: 'juicio en curso',
  convicted: 'condena',
  acquitted: 'absolución',
  dismissed: 'sobreseimiento',
  case_closed: 'causa cerrada',
  administrative_sanction: 'sanción administrativa',
  sanction_overturned: 'sanción revocada',
  unknown: 'resultado final no documentado',
} as const

const LEGAL_STATUS_EN = {
  investigation_reported: 'reported investigation',
  formally_investigated: 'formal investigation',
  charged: 'charged',
  trial_ongoing: 'trial ongoing',
  convicted: 'conviction',
  acquitted: 'acquittal',
  dismissed: 'dismissed',
  case_closed: 'case closed',
  administrative_sanction: 'administrative sanction',
  sanction_overturned: 'sanction overturned',
  unknown: 'final outcome not documented',
} as const

export default function ActorPopover({
  actor,
  trigger = 'name',
  align = 'left',
}: {
  actor: ActorProfile
  trigger?: 'name' | 'avatar'
  align?: 'left' | 'right'
}) {
  const { language, tr } = useLanguage()
  const instanceId = useId().replaceAll(':', '')
  const tooltipId = `actor-${actor.id}-${instanceId}`
  const officialCaseContext = actor.official_case_context ?? []
  const hasOfficialConcern = actor.legal_record.length > 0 || officialCaseContext.length > 0
  const auditHasAttachedEvidence = actor.official_record_audit.status !== 'no_qualifying_record_documented'
  return (
    <span className="group/actor relative inline-block">
      <button
        type="button"
        className={
          trigger === 'avatar'
            ? 'group/avatar relative block rounded-full'
            : 'rounded-sm border-b border-dotted border-ink-muted font-semibold text-ink-primary'
        }
        aria-describedby={tooltipId}
      >
        {trigger === 'avatar' ? (
          <>
            <img
              src={dataUrl(actor.image)}
              alt=""
              className={`h-11 w-11 rounded-full border-2 object-cover object-top grayscale transition group-hover/avatar:scale-105 group-hover/avatar:grayscale-0 group-focus/avatar:grayscale-0 ${
                hasOfficialConcern ? 'border-status-critical' : 'border-surface-card'
              }`}
              loading="lazy"
            />
            {hasOfficialConcern && (
              <span
                className="absolute right-0 top-0 h-2.5 w-2.5 rounded-full border border-surface-card bg-status-critical"
                aria-hidden="true"
              />
            )}
            <span className="sr-only">{actor.name}</span>
          </>
        ) : (
          actor.name
        )}
      </button>
      <span
        id={tooltipId}
        role="tooltip"
        className={`invisible absolute top-[calc(100%+0.5rem)] z-40 max-h-[min(34rem,calc(100vh-6rem))] w-[min(22rem,calc(100vw-2.5rem))] translate-y-1 overflow-y-auto border border-line-strong bg-surface-raised p-4 text-left opacity-0 shadow-xl transition duration-150 group-focus-within/actor:visible group-focus-within/actor:translate-y-0 group-focus-within/actor:opacity-100 group-hover/actor:visible group-hover/actor:translate-y-0 group-hover/actor:opacity-100 ${
          align === 'right' ? 'right-0' : 'left-0'
        }`}
      >
        <span className="flex gap-4">
          <img
            src={dataUrl(actor.image)}
            alt={actor.image_alt}
            className="h-24 w-20 shrink-0 object-cover object-top grayscale"
            loading="lazy"
          />
          <span>
            <span className="block text-caption font-semibold text-ink-primary">{actor.role}</span>
            <span className="mt-1 block text-micro uppercase text-ink-muted">
              {actor.institution} · {actor.affiliation}
            </span>
            <span className="mt-3 block text-caption font-normal text-ink-secondary">{actor.position_summary}</span>
          </span>
        </span>
        {actor.public_record.map((record) => (
          <span
            key={`${record.date}-${record.action}`}
            className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal"
          >
            <span className="block font-semibold uppercase tracking-wide text-ink-muted">
              {tr('Actuación pública', 'Public action')} · {record.date}
            </span>
            <span className="mt-1 block text-ink-primary">{record.action}</span>
            <span className="mt-1 block text-ink-secondary">{record.outcome}</span>
            <span className="mt-1 block text-ink-muted">{record.assessment}</span>
          </span>
        ))}
        {actor.legal_record.map((record) => (
          <span
            key={record.source.id}
            className="mt-3 block border-l-2 border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] p-3 text-micro font-normal"
          >
            <span className="block font-semibold uppercase tracking-wide text-status-critical">
              {tr('Registro judicial oficial', 'Official legal record')} ·{' '}
              {language === 'es' ? LEGAL_STATUS_ES[record.status] : LEGAL_STATUS_EN[record.status]}
            </span>
            <span className="mt-2 block text-ink-primary">{record.summary}</span>
            <span className="mt-2 block text-ink-muted">
              {record.body}
              {record.date ? ` · ${record.date}` : ''}
            </span>
            {record.presumption_note && (
              <span className="mt-2 block font-semibold text-ink-primary">{record.presumption_note}</span>
            )}
            <a
              href={record.source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block font-semibold text-ink-primary underline underline-offset-2"
            >
              {tr('Abrir fuente oficial', 'Open official source')} ↗
            </a>
            <span className="mt-2 block text-ink-muted">
              {tr(
                'Este antecedente no demuestra sesgo ni modifica la evaluación factual de sus afirmaciones.',
                'This record does not prove bias and does not alter the factual evaluation of this person’s claims.',
              )}
            </span>
          </span>
        ))}
        {officialCaseContext.map((record) => (
          <span
            key={record.source.id}
            className="mt-3 block border-l-2 border-status-critical bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] p-3 text-micro font-normal"
          >
            <span className="block font-semibold uppercase tracking-wide text-status-critical">
              {tr('Contexto profesional en expediente de colusión', 'Professional context in a collusion case')}
            </span>
            <span className="mt-1 block font-semibold text-ink-primary">
              {tr('No fue parte requerida ni sancionada personalmente', 'Not a defendant and not personally sanctioned')}
            </span>
            <span className="mt-2 block text-ink-primary">{record.summary}</span>
            <span className="mt-2 block text-ink-secondary">
              <span className="font-semibold">{tr('Rol documentado', 'Documented role')}:</span> {record.role}
            </span>
            <span className="mt-1 block text-ink-secondary">
              <span className="font-semibold">{tr('Resultado de la causa', 'Case outcome')}:</span> {record.outcome}
            </span>
            <span className="mt-2 block text-ink-muted">{record.relevance_to_document}</span>
            <span className="mt-2 block font-semibold text-ink-primary">{record.caveat}</span>
            <a
              href={record.source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block font-semibold text-ink-primary underline underline-offset-2"
            >
              {tr('Abrir sentencia oficial', 'Open official judgment')} ↗
            </a>
          </span>
        ))}
        <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-muted">
          <span className="font-semibold text-ink-primary">
            {tr('Revisión oficial aplicada a esta ficha', 'Official-record review applied to this profile')}:
          </span>{' '}
          {auditHasAttachedEvidence
            ? tr('evidencia incorporada arriba', 'evidence attached above')
            : tr(
                'sin antecedente personal calificable documentado al corte',
                'no qualifying personal record documented by the cutoff',
              )}
          . {actor.official_record_audit.caveat}
        </span>
        <span className="mt-2 block text-micro font-normal text-ink-muted">
          {tr('Foto', 'Photo')}: {actor.image_credit} · {actor.image_license}.{' '}
          {tr('Historial factual; no interviene en el veredicto.', 'Factual history; it does not affect the verdict.')}
        </span>
      </span>
    </span>
  )
}

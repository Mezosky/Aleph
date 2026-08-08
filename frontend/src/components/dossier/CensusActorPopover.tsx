import { dataUrl } from '@/lib/data'
import type { CensusActor } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

export default function CensusActorPopover({ actor }: { actor: CensusActor }) {
  const { tr } = useLanguage()
  const affiliation =
    actor.affiliation_status === 'institutional_not_applicable'
      ? tr('Afiliación partidaria no aplica', 'Party affiliation does not apply')
      : actor.affiliation_status === 'not_documented'
        ? tr('Afiliación no documentada', 'Affiliation not documented')
        : actor.affiliation
  return (
    <span className="group/census relative inline-block">
      <button
        type="button"
        className="text-left font-semibold underline decoration-line-strong underline-offset-4"
        aria-describedby={`census-actor-${actor.id}`}
      >
        {actor.name}
      </button>
      <span
        id={`census-actor-${actor.id}`}
        role="tooltip"
        className="invisible absolute left-0 top-[calc(100%+0.5rem)] z-40 w-[min(22rem,calc(100vw-2.5rem))] translate-y-1 border border-line-strong bg-surface-raised p-4 text-left opacity-0 shadow-xl transition duration-150 group-focus-within/census:visible group-focus-within/census:translate-y-0 group-focus-within/census:opacity-100 group-hover/census:visible group-hover/census:translate-y-0 group-hover/census:opacity-100"
      >
        <span className="flex gap-4">
          {actor.image && (
            <img
              src={dataUrl(actor.image)}
              alt={actor.image_alt || `${tr('Retrato de', 'Portrait of')} ${actor.name}`}
              className="h-24 w-20 shrink-0 object-cover object-top grayscale"
              loading="lazy"
            />
          )}
          <span>
            <span className="block text-caption font-semibold text-ink-primary">
              {actor.role || tr('Rol no especificado en la captura', 'Role not specified in the capture')}
            </span>
            {(actor.institution || affiliation) && (
              <span className="mt-1 block text-micro text-ink-muted">
                {[actor.institution, affiliation].filter(Boolean).join(' · ')}
              </span>
            )}
            <span className="mt-3 block text-caption font-normal text-ink-secondary">
              {actor.participation_summary}
            </span>
          </span>
        </span>
        {actor.affiliation_source_url && (
          <a
            href={actor.affiliation_source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-3 block border-t border-line-hairline pt-3 text-micro font-semibold text-ink-primary underline decoration-line-strong underline-offset-4"
          >
            {tr('Afiliación en registro público', 'Affiliation in public record')} · {actor.affiliation_verified_at}
          </a>
        )}
        {actor.public_record?.[0] && (
          <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-secondary">
            <span className="font-semibold text-ink-primary">{tr('Historial verificado', 'Verified record')}:</span>{' '}
            {actor.public_record[0].action} {actor.public_record[0].assessment}
          </span>
        )}
        <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-muted">
          {actor.source_ids.length}{' '}
          {actor.source_ids.length === 1
            ? tr('fuente archivada', 'archived source')
            : tr('fuentes archivadas', 'archived sources')}{' '}
          ·{' '}
          {actor.profile_depth === 'detailed'
            ? tr('ficha ampliada disponible', 'expanded profile available')
            : tr('sólo índice documental', 'document index only')}
          .{' '}
          {tr(
            'La trayectoria atribuida no altera ningún veredicto ciego.',
            'The attributed record does not alter any blind verdict.',
          )}
        </span>
        {actor.image && (
          <span className="mt-2 block text-micro font-normal text-ink-muted">
            {tr('Foto', 'Photo')}: {actor.image_credit} · {actor.image_license}.
          </span>
        )}
      </span>
    </span>
  )
}

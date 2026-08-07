import { dataUrl } from '@/lib/data'
import type { CensusActor } from '@/types/megareforma'

export default function CensusActorPopover({ actor }: { actor: CensusActor }) {
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
              alt={actor.image_alt || `Retrato de ${actor.name}`}
              className="h-24 w-20 shrink-0 object-cover object-top grayscale"
              loading="lazy"
            />
          )}
          <span>
            <span className="block text-caption font-semibold text-ink-primary">
              {actor.role || 'Rol no especificado en la captura'}
            </span>
            {(actor.institution || actor.affiliation) && (
              <span className="mt-1 block text-micro text-ink-muted">
                {[actor.institution, actor.affiliation].filter(Boolean).join(' · ')}
              </span>
            )}
            <span className="mt-3 block text-caption font-normal text-ink-secondary">
              {actor.participation_summary}
            </span>
          </span>
        </span>
        {actor.public_record?.[0] && (
          <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-secondary">
            <span className="font-semibold text-ink-primary">Historial verificado:</span>{' '}
            {actor.public_record[0].action} {actor.public_record[0].assessment}
          </span>
        )}
        <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-muted">
          {actor.source_ids.length} {actor.source_ids.length === 1 ? 'fuente archivada' : 'fuentes archivadas'} ·{' '}
          {actor.profile_depth === 'detailed' ? 'ficha ampliada disponible' : 'sólo índice documental'}.
          La trayectoria atribuida no altera ningún veredicto ciego.
        </span>
        {actor.image && (
          <span className="mt-2 block text-micro font-normal text-ink-muted">
            Foto: {actor.image_credit} · {actor.image_license}.
          </span>
        )}
      </span>
    </span>
  )
}

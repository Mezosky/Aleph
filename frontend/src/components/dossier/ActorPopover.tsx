import { dataUrl } from '@/lib/data'
import type { ActorProfile } from '@/types/megareforma'

export default function ActorPopover({ actor }: { actor: ActorProfile }) {
  return (
    <span className="group/actor relative inline-block">
      <button
        type="button"
        className="rounded-sm border-b border-dotted border-ink-muted font-semibold text-ink-primary"
        aria-describedby={`actor-${actor.id}`}
      >
        {actor.name}
      </button>
      <span
        id={`actor-${actor.id}`}
        role="tooltip"
        className="invisible absolute left-0 top-[calc(100%+0.5rem)] z-40 w-[min(22rem,calc(100vw-2.5rem))] translate-y-1 border border-line-strong bg-surface-raised p-4 text-left opacity-0 shadow-xl transition duration-150 group-focus-within/actor:visible group-focus-within/actor:translate-y-0 group-focus-within/actor:opacity-100 group-hover/actor:visible group-hover/actor:translate-y-0 group-hover/actor:opacity-100"
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
        <span className="mt-3 block border-t border-line-hairline pt-3 text-micro font-normal text-ink-muted">
          {actor.public_record[0]?.assessment}
        </span>
        <span className="mt-2 block text-micro font-normal text-ink-muted">
          Foto: {actor.image_credit} · {actor.image_license}. Historial factual; no interviene en el veredicto.
        </span>
      </span>
    </span>
  )
}

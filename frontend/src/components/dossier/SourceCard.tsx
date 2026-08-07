import { dataUrl } from '@/lib/data'
import type { CapturedSource } from '@/types/megareforma'

export default function SourceCard({ source }: { source: CapturedSource }) {
  return (
    <article className="group flex h-full flex-col overflow-hidden border border-line-hairline bg-surface-card">
      <a
        href={source.original_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block overflow-hidden bg-surface-sunken"
      >
        <img
          src={dataUrl(source.screenshot)}
          alt={`Captura archivada del artículo en ${source.publisher}`}
          className="aspect-[16/10] w-full object-cover object-top grayscale transition duration-300 group-hover:scale-[1.015] group-hover:grayscale-0"
          loading="lazy"
        />
      </a>
      <div className="flex flex-1 flex-col p-4">
        <p className="text-micro uppercase tracking-wide text-ink-muted">
          {source.publisher} · {source.kind === 'official_record' ? 'registro oficial' : 'prensa'}
        </p>
        <h3 className="mt-2 text-body font-semibold leading-snug text-ink-primary">{source.title}</h3>
        {source.summary && <p className="mt-2 line-clamp-3 text-caption text-ink-secondary">{source.summary}</p>}
        <a
          href={source.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-auto pt-4 text-caption font-semibold text-ink-primary underline underline-offset-4"
        >
          Abrir publicación original ↗
        </a>
      </div>
    </article>
  )
}

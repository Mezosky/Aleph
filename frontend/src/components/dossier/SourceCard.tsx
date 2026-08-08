import { dataUrl } from '@/lib/data'
import type { CapturedSource } from '@/types/megareforma'
import { useLanguage } from '@/i18n/LanguageContext'

export default function SourceCard({ source }: { source: CapturedSource }) {
  const { tr } = useLanguage()
  const kindLabel =
    source.kind === 'official_record'
      ? tr('registro oficial', 'official record')
      : source.kind === 'research'
        ? tr('evidencia comparada', 'comparative evidence')
        : tr('prensa', 'press')
  const formatLabel =
    source.format === 'video'
      ? 'video'
      : source.format === 'audio'
        ? 'audio'
        : source.format === 'transcript'
          ? tr('transcripción', 'transcript')
          : null
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
          alt={`${tr('Captura archivada del artículo en', 'Archived capture of the article at')} ${source.publisher}`}
          className="aspect-[16/10] w-full object-cover object-top grayscale transition duration-300 group-hover:scale-[1.015] group-hover:grayscale-0"
          loading="lazy"
        />
      </a>
      <div className="flex flex-1 flex-col p-4">
        <p className="text-micro uppercase tracking-wide text-ink-muted">
          {source.publisher} · {kindLabel}
          {formatLabel ? ` · ${formatLabel}` : ''}
        </p>
        <h3 className="mt-2 text-body font-semibold leading-snug text-ink-primary">{source.title}</h3>
        {source.summary && <p className="mt-2 line-clamp-3 text-caption text-ink-secondary">{source.summary}</p>}
        <a
          href={source.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-auto pt-4 text-caption font-semibold text-ink-primary underline underline-offset-4"
        >
          {source.format === 'video'
            ? tr('Ver video original ↗', 'Watch original video ↗')
            : source.format === 'audio'
              ? tr('Escuchar original ↗', 'Listen to original ↗')
              : tr('Abrir publicación original ↗', 'Open original publication ↗')}
        </a>
      </div>
    </article>
  )
}

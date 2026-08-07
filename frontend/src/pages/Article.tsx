import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { describeDataError, loadAnalysis, loadLatestNews } from '@/lib/data'
import { formatDateTime } from '@/lib/format'
import type { AnalysisBundle, NewsFeedItem } from '@/types/aleph'

export default function Article() {
  const { id = '' } = useParams()
  const [item, setItem] = useState<NewsFeedItem | null>(null)
  const [bundle, setBundle] = useState<AnalysisBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    loadLatestNews(controller.signal).then(async (feed) => {
      const match = feed.items.find((candidate) => candidate.article.id === id)
      if (!match) throw new Error('La noticia solicitada no está en el conjunto publicado.')
      setItem(match)
      if (match.document_slug) setBundle(await loadAnalysis(match.document_slug, controller.signal))
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(describeDataError(reason))
    })
    return () => controller.abort()
  }, [id])

  if (error) return <p role="alert" className="text-body text-ink-primary">{error}</p>
  if (!item) return <p role="status" className="text-body text-ink-secondary">Cargando contraste…</p>
  const claims = bundle?.claims.filter((claim) => item.article.claim_ids.includes(claim.id)) ?? []

  return (
    <article>
      <header className="max-w-4xl"><p className="text-micro uppercase tracking-wide text-ink-muted">Artículo · datos sintéticos</p><h1 className="mt-3 text-display font-semibold">{item.article.headline}</h1><p className="mt-5 text-caption text-ink-secondary">{item.article.publisher.name} · {formatDateTime(item.article.published_at)}</p></header>
      <div className="mt-12 grid gap-8 lg:grid-cols-2">
        <section className="border border-line-hairline bg-surface-card p-6"><p className="text-micro uppercase text-ink-muted">Artículo original</p><h2 className="mt-3 text-title font-semibold">Resumen neutral</h2><p className="mt-4 text-body text-ink-secondary">{item.article.neutral_summary}</p>{item.article.url ? <a href={item.article.url} className="mt-5 inline-block text-caption underline">Abrir fuente</a> : <p className="mt-5 text-caption text-ink-muted">La demostración sintética no enlaza una publicación real.</p>}</section>
        <section className="border-2 border-line-strong p-6"><p className="text-micro uppercase text-ink-muted">Análisis Aleph · veredicto ciego</p><h2 className="mt-3 text-title font-semibold">{claims.length} afirmaciones detectadas</h2><ul className="mt-5 space-y-4">{claims.map((claim) => <li key={claim.id} className="border-t border-line-hairline pt-4"><p className="text-caption font-semibold">{claim.blind_evaluation.verdict}</p><p className="mt-2 text-body">{claim.text}</p></li>)}</ul></section>
      </div>
      <section className="mt-14 border-t border-line-hairline pt-10"><h2 className="text-title font-semibold">Cómo se está contando</h2><p className="mt-3 max-w-prose text-body text-ink-secondary">La comparación agrupa publicaciones por origen y muestra sus énfasis sin convertirlos en una etiqueta de sesgo.</p><p className="mt-5 text-caption">Fuentes originales distintas: <strong>{item.independent_source_count ?? 0}</strong></p></section>
      {item.document_slug && <Link to={`/documento/${item.document_slug}`} className="mt-10 inline-block text-caption font-semibold underline underline-offset-4">Volver al documento →</Link>}
    </article>
  )
}

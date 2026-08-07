import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { describeDataError, loadLatestNews, loadSiteIndex } from '@/lib/data'
import { relativeTime } from '@/lib/format'
import type { NewsFeed, SiteIndex } from '@/types/aleph'

export default function Home() {
  const [index, setIndex] = useState<SiteIndex | null>(null)
  const [news, setNews] = useState<NewsFeed | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([loadSiteIndex(controller.signal), loadLatestNews(controller.signal)]).then(
      ([siteIndex, feed]) => {
        setIndex(siteIndex)
        setNews(feed)
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(describeDataError(reason))
      },
    )
    return () => controller.abort()
  }, [])

  const featured = index?.analyses.find((entry) => entry.slug === index.featured) ?? index?.analyses[0]

  return (
    <>
      <section className="max-w-4xl py-8 sm:py-16">
        <p className="text-micro font-semibold uppercase tracking-[0.2em] text-ink-muted">א · Aleph</p>
        <h1 className="mt-5 max-w-3xl text-display font-semibold text-ink-primary">
          Entiende la evidencia detrás del debate público.
        </h1>
        <p className="mt-6 max-w-prose text-lede text-ink-secondary">
          Del documento a las afirmaciones, y de cada afirmación a la evidencia. Sin puntajes de
          reputación y con el veredicto factual ciego a quien habla.
        </p>
        <Link to="/analizar" className="mt-8 inline-flex rounded-data bg-ink-primary px-5 py-3 text-caption font-semibold text-ink-inverse">
          Analizar documento
        </Link>
      </section>

      {error && <p role="alert" className="border border-status-critical p-4 text-body text-ink-primary">{error}</p>}

      {featured && (
        <section aria-labelledby="featured-heading" className="mt-12 border-t border-line-hairline pt-10">
          <p className="text-micro uppercase tracking-wide text-ink-muted">Análisis destacado · datos sintéticos</p>
          <div className="mt-4 grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <h2 id="featured-heading" className="max-w-3xl text-title font-semibold text-ink-primary">{featured.title}</h2>
              <p className="mt-4 max-w-prose text-body text-ink-secondary">{featured.summary}</p>
            </div>
            <Link to={`/documento/${featured.slug}`} className="text-caption font-semibold text-ink-primary underline underline-offset-4">Ver análisis →</Link>
          </div>
          <dl className="mt-8 grid grid-cols-2 gap-px bg-line-hairline sm:grid-cols-4">
            {Object.entries(featured.counts ?? {}).slice(0, 4).map(([label, value]) => (
              <div key={label} className="bg-surface-card p-4"><dt className="text-micro uppercase text-ink-muted">{label}</dt><dd className="mt-2 text-title tabular text-ink-primary">{value}</dd></div>
            ))}
          </dl>
        </section>
      )}

      <section aria-labelledby="news-heading" className="mt-20 border-t border-line-hairline pt-10">
        <div className="max-w-prose"><p className="text-micro uppercase tracking-wide text-ink-muted">Discurso público</p><h2 id="news-heading" className="mt-2 text-title font-semibold">Últimas noticias</h2><p className="mt-3 text-body text-ink-secondary">No contamos publicaciones: mostramos afirmaciones, veredictos e independencia de fuentes.</p></div>
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {news?.items.slice(0, 6).map((item) => (
            <article key={item.article.id} className="flex flex-col border border-line-hairline bg-surface-card p-5">
              <p className="text-micro text-ink-muted">{item.article.publisher.name} · {relativeTime(item.article.published_at)}</p>
              <h3 className="mt-3 text-lede font-semibold text-ink-primary">{item.article.headline}</h3>
              <p className="mt-3 line-clamp-3 text-caption text-ink-secondary">{item.article.neutral_summary}</p>
              <p className="mt-5 text-caption text-ink-secondary">{item.claim_count ?? item.article.claim_ids.length} afirmaciones · {item.independent_source_count ?? 0} fuentes originales</p>
              <Link to={`/noticia/${encodeURIComponent(item.article.id)}`} className="mt-5 text-caption font-semibold underline underline-offset-4">Ver contraste →</Link>
            </article>
          ))}
        </div>
      </section>
    </>
  )
}

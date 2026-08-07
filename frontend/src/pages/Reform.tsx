import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ActorProfileSection from '@/components/actors/ActorProfileSection'
import { describeDataError, getPropositions, loadAnalysis } from '@/lib/data'
import { formatConfidence, formatDateTime } from '@/lib/format'
import type { AnalysisBundle } from '@/types/aleph'

export default function Reform() {
  const { slug = '' } = useParams()
  const [bundle, setBundle] = useState<AnalysisBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    loadAnalysis(slug, controller.signal).then(setBundle, (reason: unknown) => {
      if (!controller.signal.aborted) setError(describeDataError(reason))
    })
    return () => controller.abort()
  }, [slug])

  if (error) return <section><h1 className="text-title font-semibold">No pudimos cargar el análisis</h1><p className="mt-4 text-body text-ink-secondary">{error}</p></section>
  if (!bundle) return <p role="status" className="text-body text-ink-secondary">Cargando análisis…</p>

  const propositions = getPropositions(bundle)
  return (
    <article>
      {bundle.data_status === 'synthetic' && <p role="note" className="border-l-4 border-status-warning bg-surface-sunken p-4 text-caption text-ink-primary"><strong>Demostración sintética.</strong> No describe declaraciones ni publicaciones reales.</p>}
      <header className="mt-8 max-w-4xl">
        <p className="text-micro uppercase tracking-wide text-ink-muted">{bundle.document.identity.document_type} · {bundle.document.identity.status}</p>
        <h1 className="mt-3 text-display font-semibold">{bundle.document.identity.title}</h1>
        <p className="mt-5 max-w-prose text-lede text-ink-secondary">{bundle.document.identity.summary}</p>
        <dl className="mt-8 flex flex-wrap gap-x-8 gap-y-4 text-caption"><div><dt className="text-ink-muted">Preparación</dt><dd className="mt-1 font-semibold">{bundle.readiness.overall_score}/100</dd></div><div><dt className="text-ink-muted">Confianza de evidencia</dt><dd className="mt-1 font-semibold">{formatConfidence(bundle.readiness.confidence.evidence_confidence)}</dd></div><div><dt className="text-ink-muted">Generado</dt><dd className="mt-1 font-semibold">{formatDateTime(bundle.generated_at)}</dd></div></dl>
      </header>

      <nav aria-label="Secciones del análisis" className="mt-10 overflow-x-auto border-y border-line-hairline py-3 text-caption"><div className="flex min-w-max gap-6">{['resumen','medidas','impacto','afirmaciones','evidencia','actores','metodologia'].map((item) => <a key={item} href={`#${item}`} className="capitalize text-ink-secondary hover:text-ink-primary">{item}</a>)}</div></nav>

      <section id="resumen" className="mt-14"><h2 className="text-title font-semibold">Qué dice el documento</h2><p className="mt-3 text-body text-ink-secondary">{propositions.length} proposiciones atómicas, cada una ligada a un pasaje verificable.</p></section>
      <section id="medidas" className="mt-10 grid gap-4 md:grid-cols-2">{bundle.provisions.slice(0, 8).map((provision) => <article key={provision.id} className="border border-line-hairline p-5"><p className="text-micro text-ink-muted">{provision.ref_label ?? provision.id}</p><h3 className="mt-2 text-lede font-semibold">{provision.title}</h3><p className="mt-3 text-caption text-ink-secondary">{provision.summary}</p></article>)}</section>

      <section id="afirmaciones" className="mt-16 border-t border-line-hairline pt-10"><h2 className="text-title font-semibold">Afirmaciones evaluadas</h2><div className="mt-6 space-y-4">{bundle.claims.map((claim) => <article id={claim.id} key={claim.id} className="scroll-mt-24 border border-line-hairline bg-surface-card p-5"><div className="flex flex-wrap justify-between gap-3"><span className="text-micro uppercase text-ink-muted">{claim.statement_type}</span><span className="text-caption font-semibold">{claim.blind_evaluation.verdict}</span></div><p className="mt-3 text-body text-ink-primary">{claim.text}</p><details className="mt-4"><summary className="cursor-pointer text-caption font-semibold">Ver razonamiento y evidencia</summary><p className="mt-3 text-caption text-ink-secondary">{claim.blind_evaluation.reasoning}</p></details></article>)}</div></section>

      <div id="actores"><ActorProfileSection profiles={bundle.actor_profiles?.actors ?? []} claims={bundle.claims} /></div>
      <section id="evidencia" className="mt-16 border-t border-line-hairline pt-10"><h2 className="text-title font-semibold">Evidencia</h2><p className="mt-3 text-body text-ink-secondary">{bundle.evidence.length} piezas; la autoridad de la fuente no sustituye su relevancia para la pregunta.</p></section>
      <section id="metodologia" className="mt-16 border-t border-line-hairline pt-10"><h2 className="text-title font-semibold">Método y límites</h2><ul className="mt-4 max-w-prose list-disc space-y-2 pl-5 text-body text-ink-secondary">{bundle.methodology.limitations.map((item) => <li key={item}>{item}</li>)}</ul><Link to="/metodologia" className="mt-5 inline-block text-caption font-semibold underline underline-offset-4">Leer metodología completa →</Link></section>
    </article>
  )
}

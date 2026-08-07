import { useState, type FormEvent } from 'react'
import { getAnalysis, isApiConfigured, pollStatus, submitAnalysis, type AnalysisStatus } from '@/lib/api'
import { WARM_PHASES } from '@/types/aleph'

export default function Analyze() {
  const configured = isApiConfigured()
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | undefined>()
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const created = await submitAnalysis(file ? { file } : { url })
      const handle = pollStatus(created.id, setStatus)
      const terminal = await handle.done
      if (terminal.state === 'failed') throw new Error(terminal.error ?? 'El análisis falló.')
      await getAnalysis(created.id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo iniciar el análisis.')
    }
  }

  return (
    <section className="max-w-4xl">
      <p className="text-micro uppercase tracking-wide text-ink-muted">Modo B</p><h1 className="mt-3 text-display font-semibold">Analizar un documento</h1><p className="mt-5 max-w-prose text-lede text-ink-secondary">Aleph primero entiende el documento y construye su ecosistema de evidencia. Si falta cobertura, se detiene antes del veredicto.</p>
      {!configured && <p role="note" className="mt-8 border-l-4 border-status-warning bg-surface-sunken p-4 text-body"><strong>Modo estático.</strong> Este despliegue no está conectado a una API. Los análisis precomputados siguen disponibles.</p>}
      <form onSubmit={submit} className="mt-10 space-y-5 border border-line-hairline bg-surface-card p-6">
        <label className="block text-caption font-semibold">Archivo PDF<input disabled={!configured} type="file" accept="application/pdf,text/plain" onChange={(event) => { setFile(event.target.files?.[0]); setUrl('') }} className="mt-2 block w-full text-caption" /></label>
        <p className="text-center text-micro uppercase text-ink-muted">o</p>
        <label className="block text-caption font-semibold">URL pública<input disabled={!configured || Boolean(file)} type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…/documento.pdf" className="mt-2 w-full border border-line-strong bg-surface-page px-3 py-2 text-body" /></label>
        <button disabled={!configured || (!file && !url.trim())} className="rounded-data bg-ink-primary px-5 py-3 text-caption font-semibold text-ink-inverse disabled:opacity-40">Iniciar análisis</button>
      </form>
      {error && <p role="alert" className="mt-5 border border-status-critical p-4 text-caption">{error}</p>}
      <ol className="mt-10 grid gap-2 sm:grid-cols-2">
        {WARM_PHASES.map((phase, index) => { const current = status?.phases.find((entry) => entry.phase === phase); return <li key={phase} className="border border-line-hairline p-4"><span className="text-micro text-ink-muted">{index + 1}</span><p className="mt-1 text-caption font-semibold">{phase.replaceAll('_', ' ')}</p><p className="mt-1 text-micro text-ink-muted">{current?.state ?? 'not_started'}</p></li> })}
      </ol>
    </section>
  )
}

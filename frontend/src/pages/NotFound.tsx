import { Link } from 'react-router-dom'

export default function NotFound() {
  return <section className="max-w-prose"><p className="text-micro uppercase text-ink-muted">404</p><h1 className="mt-3 text-title font-semibold">Esta página no existe</h1><p className="mt-4 text-body text-ink-secondary">El enlace puede apuntar a un análisis que aún no fue publicado.</p><Link to="/" className="mt-6 inline-block text-caption font-semibold underline underline-offset-4">Volver al inicio</Link></section>
}

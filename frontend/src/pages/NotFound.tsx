import { Link } from 'react-router-dom'
import { useLanguage } from '@/i18n/LanguageContext'

export default function NotFound() {
  const { tr } = useLanguage()
  return (
    <section className="max-w-prose">
      <p className="text-micro uppercase text-ink-muted">404</p>
      <h1 className="mt-3 text-title font-semibold">{tr('Esta página no existe', 'This page does not exist')}</h1>
      <p className="mt-4 text-body text-ink-secondary">
        {tr(
          'El enlace puede apuntar a un análisis que aún no fue publicado.',
          'The link may point to an analysis that has not yet been published.',
        )}
      </p>
      <Link to="/" className="mt-6 inline-block text-caption font-semibold underline underline-offset-4">
        {tr('Volver al inicio', 'Back to home')}
      </Link>
    </section>
  )
}

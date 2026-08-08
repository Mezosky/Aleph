/**
 * Application shell and routing.
 *
 * `HashRouter` is required, not preferred: GitHub Pages serves static files
 * with no SPA rewrite, so a path route would 404 on refresh or on a shared
 * link. `public/404.html` catches the remaining case — someone landing on a
 * path URL — and bounces it into the equivalent hash route.
 *
 * Page modules are code-split. Every one of them is a default export written by
 * another part of the build; this file only wires them up, resets scroll on
 * navigation, and makes sure a thrown render error becomes a readable message
 * rather than a blank page.
 */

import { Component, Suspense, lazy, useEffect, useRef, type ReactNode } from 'react'
import { HashRouter, Link, Route, Routes, useLocation } from 'react-router-dom'
import Layout from '@/components/shell/Layout'
import { LanguageProvider } from '@/i18n/LanguageContext'

const Home = lazy(() => import('@/pages/Home'))
const Actors = lazy(() => import('@/pages/Actors'))
const Reform = lazy(() => import('@/pages/Reform'))
const Methodology = lazy(() => import('@/pages/Methodology'))
const NotFound = lazy(() => import('@/pages/NotFound'))

/* ------------------------------------------------------------------ *
 * Loading state
 * ------------------------------------------------------------------ */

function SkeletonBar({ className }: { className: string }) {
  return (
    <div className={`relative overflow-hidden rounded-data bg-surface-sunken ${className}`}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-surface-raised opacity-40" />
    </div>
  )
}

/** Shown while a route module is still downloading. */
function PageSkeleton() {
  return (
    <div role="status" aria-live="polite" className="animate-fade-up">
      <span className="sr-only">Cargando la página…</span>
      <SkeletonBar className="h-3 w-28" />
      <SkeletonBar className="mt-6 h-10 w-full max-w-prose" />
      <SkeletonBar className="mt-3 h-10 w-2/3 max-w-prose" />
      <SkeletonBar className="mt-10 h-4 w-full max-w-prose" />
      <SkeletonBar className="mt-3 h-4 w-5/6 max-w-prose" />
      <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <SkeletonBar className="h-36" />
        <SkeletonBar className="h-36" />
        <SkeletonBar className="h-36" />
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * Error boundary
 * ------------------------------------------------------------------ */

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * A render error must produce a stated failure, not an empty screen. In a
 * product about evidence, silence is the one thing an interface may not do.
 */
class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error) {
    // Surfaced in the console for a developer; the reader gets the panel below.
    console.error('[aleph] error de renderizado', error)
  }

  private reset = () => {
    this.setState({ error: null })
  }

  override render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <section aria-labelledby="app-error-heading" className="max-w-prose py-8">
        <p className="text-micro uppercase tracking-wide text-ink-muted">Error</p>
        <h1 id="app-error-heading" className="mt-3 text-title font-semibold text-ink-primary">
          Esta vista no pudo mostrarse
        </h1>
        <p className="mt-4 text-body text-ink-secondary">
          Algo falló al construir la página. No se perdió ningún dato: el análisis se sirve como archivos estáticos y
          puedes volver a intentarlo.
        </p>
        <p className="mt-4 rounded-data border border-line-hairline bg-surface-sunken p-4 font-mono text-caption text-ink-secondary">
          {error.message || 'Error desconocido'}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={this.reset}
            className="rounded-data border border-line-strong px-4 py-2 text-caption text-ink-primary transition-colors duration-200 ease-subtle hover:bg-surface-sunken"
          >
            Reintentar
          </button>
          <Link
            to="/"
            onClick={this.reset}
            className="rounded-data border border-line-hairline px-4 py-2 text-caption text-ink-secondary transition-colors duration-200 ease-subtle hover:text-ink-primary"
          >
            Volver al inicio
          </Link>
        </div>
      </section>
    )
  }
}

/* ------------------------------------------------------------------ *
 * Navigation side effects
 * ------------------------------------------------------------------ */

/**
 * Reset scroll on navigation and move focus to the main region, so a keyboard
 * or screen-reader user does not land at the bottom of the previous page. The
 * first render is skipped: stealing focus on load is its own annoyance.
 */
function ScrollToTop() {
  const { pathname } = useLocation()
  const first = useRef(true)

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
    const main = document.getElementById('content')
    if (main instanceof HTMLElement) main.focus({ preventScroll: true })
  }, [pathname])

  return null
}

/* ------------------------------------------------------------------ *
 * App
 * ------------------------------------------------------------------ */

export default function App() {
  return (
    <LanguageProvider>
      <HashRouter>
        <ScrollToTop />
        <Layout>
          <ErrorBoundary>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/actores" element={<Actors />} />
                <Route path="/documento/:slug" element={<Reform />} />
                <Route path="/metodologia" element={<Methodology />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </Layout>
      </HashRouter>
    </LanguageProvider>
  )
}

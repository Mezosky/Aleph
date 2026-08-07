/**
 * Site footer.
 *
 * The synthetic-data disclaimer appears here on every page. It is not a
 * substitute for the banner that analysis views carry — it is the floor. A
 * reader must never be able to reach a screen of this product without being
 * told what the data is.
 */

import { Link } from 'react-router-dom'
import { ALEPH_SCHEMA_VERSION } from '@/types/aleph'

const REPO_URL = 'https://github.com/Mezosky/Aleph'

export default function Footer() {
  return (
    <footer className="mt-24 border-t border-line-hairline">
      <div className="mx-auto w-full max-w-shell px-5 py-12 sm:px-8">
        <div className="flex flex-col gap-10 md:flex-row md:justify-between">
          <div className="max-w-prose">
            <p className="flex items-baseline gap-2.5">
              <span aria-hidden="true" className="font-serif text-lede leading-none text-ink-primary">
                א
              </span>
              <span className="text-caption font-semibold uppercase tracking-[0.22em] text-ink-primary">
                Aleph
              </span>
            </p>
            <p className="mt-3 text-body text-ink-secondary">
              Aleph lee un documento público, extrae sus afirmaciones, las contrasta con la fuente
              primaria sin saber quién las hizo, y muestra la evidencia y las contradicciones para que
              cualquiera pueda revisarlas.
            </p>
          </div>

          <nav aria-label="Pie de página" className="shrink-0">
            <ul className="flex flex-col gap-2 text-caption">
              <li>
                <Link
                  to="/metodologia"
                  className="text-ink-secondary underline-offset-4 transition-colors duration-200 ease-subtle hover:text-ink-primary hover:underline"
                >
                  Metodología y límites
                </Link>
              </li>
              <li>
                <Link
                  to="/analizar"
                  className="text-ink-secondary underline-offset-4 transition-colors duration-200 ease-subtle hover:text-ink-primary hover:underline"
                >
                  Analizar un documento
                </Link>
              </li>
              <li>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-ink-secondary underline-offset-4 transition-colors duration-200 ease-subtle hover:text-ink-primary hover:underline"
                >
                  Código fuente en GitHub
                  <span className="sr-only"> (se abre en una pestaña nueva)</span>
                </a>
              </li>
            </ul>
          </nav>
        </div>

        <p
          role="note"
          className="mt-10 max-w-prose border-l-2 border-line-strong pl-4 text-caption text-ink-secondary"
        >
          <span className="font-semibold text-ink-primary">Datos sintéticos.</span> El análisis de
          ejemplo incluido en este sitio fue generado para demostrar el producto. No describe ninguna
          declaración real de ninguna persona ni de ningún medio real, y no debe citarse como análisis
          de una reforma real.
        </p>

        <p className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-1 text-micro uppercase tracking-wide text-ink-muted">
          <span className="tabular">Contrato de datos v{ALEPH_SCHEMA_VERSION}</span>
          <span aria-hidden="true">·</span>
          <span>Sin puntaje de sesgo. Sin eje izquierda–derecha.</span>
        </p>
      </div>
    </footer>
  )
}

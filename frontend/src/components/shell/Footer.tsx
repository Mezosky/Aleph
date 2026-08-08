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
import { useLanguage } from '@/i18n/LanguageContext'

const REPO_URL = 'https://github.com/Mezosky/Aleph'

export default function Footer() {
  const { tr } = useLanguage()
  return (
    <footer className="mt-24 border-t border-line-hairline">
      <div className="mx-auto w-full max-w-shell px-5 py-12 sm:px-8">
        <div className="flex flex-col gap-10 md:flex-row md:justify-between">
          <div className="max-w-prose">
            <p className="flex items-baseline gap-2.5">
              <span aria-hidden="true" className="font-serif text-lede leading-none text-ink-primary">
                א
              </span>
              <span className="text-caption font-semibold uppercase tracking-[0.22em] text-ink-primary">Aleph</span>
            </p>
            <p className="mt-3 text-body text-ink-secondary">
              {tr(
                'Aleph lee un documento público, extrae sus afirmaciones, las contrasta con la fuente primaria sin saber quién las hizo, y muestra la evidencia y las contradicciones para que cualquiera pueda revisarlas.',
                'Aleph reads a public document, extracts its claims, checks them against primary sources without knowing who made them, and displays the evidence and contradictions for anyone to inspect.',
              )}
            </p>
          </div>

          <nav aria-label={tr('Pie de página', 'Footer')} className="shrink-0">
            <ul className="flex flex-col gap-2 text-caption">
              <li>
                <Link
                  to="/metodologia"
                  className="text-ink-secondary underline-offset-4 transition-colors duration-200 ease-subtle hover:text-ink-primary hover:underline"
                >
                  {tr('Metodología y límites', 'Methodology and limitations')}
                </Link>
              </li>
              <li>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-ink-secondary underline-offset-4 transition-colors duration-200 ease-subtle hover:text-ink-primary hover:underline"
                >
                  {tr('Código fuente en GitHub', 'Source code on GitHub')}
                  <span className="sr-only"> {tr('(se abre en una pestaña nueva)', '(opens in a new tab)')}</span>
                </a>
              </li>
            </ul>
          </nav>
        </div>

        <p role="note" className="mt-10 max-w-prose border-l-2 border-line-strong pl-4 text-caption text-ink-secondary">
          <span className="font-semibold text-ink-primary">
            {tr('Instantánea real y congelada.', 'Real, frozen snapshot.')}
          </span>{' '}
          {tr(
            'Este despliegue sólo presenta el informe financiero DIPRES N°84 de 22 de abril de 2026 y fuentes recuperadas hasta la fecha de corte indicada. El modelo se ejecutó localmente; esta página no llama a una IA ni analiza documentos del visitante.',
            'This deployment presents only DIPRES financial report No. 84 of April 22, 2026 and sources retrieved by the stated cutoff. The model ran locally; this page does not call an AI or analyze visitor documents.',
          )}
        </p>

        <p className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-1 text-micro uppercase tracking-wide text-ink-muted">
          <span className="tabular">
            {tr('Contrato de datos', 'Data contract')} v{ALEPH_SCHEMA_VERSION}
          </span>
          <span aria-hidden="true">·</span>
          <span>
            {tr(
              'Perfiles separados del veredicto · medidores con componentes auditables',
              'Profiles separated from verdicts · meters with auditable components',
            )}
          </span>
        </p>
      </div>
    </footer>
  )
}

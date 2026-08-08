import { useEffect, useState } from 'react'
import { useLanguage } from '@/i18n/LanguageContext'

interface SectionDefinition {
  id: string
  es: string
  en: string
}

const SECTIONS: readonly SectionDefinition[] = [
  { id: 'resumen', es: 'Resumen', en: 'Overview' },
  { id: 'medidores', es: 'Medidores', en: 'Meters' },
  { id: 'objetivos', es: 'La reforma', en: 'The reform' },
  { id: 'debate', es: 'Debate público', en: 'Public debate' },
  { id: 'evidencia-comparada', es: 'Evidencia global', en: 'Global evidence' },
]
const FIRST_SECTION_ID = 'resumen'
const REGION_BANDS = [
  { es: 'Norte Grande', en: 'Far North', x: 20, y: 18 },
  { es: 'Norte Chico', en: 'Near North', x: 24, y: 64 },
  { es: 'Zona Central', en: 'Central Chile', x: 18, y: 110 },
  { es: 'Zona Sur', en: 'Southern Chile', x: 23, y: 156 },
  { es: 'Zona Austral', en: 'Austral Chile', x: 18, y: 204 },
] as const

function ChileProgress({ activeIndex, compact = false }: { activeIndex: number; compact?: boolean }) {
  const { language, tr } = useLanguage()
  const region = REGION_BANDS[activeIndex] ?? REGION_BANDS[0]
  return (
    <svg
      viewBox="0 0 44 224"
      role="img"
      aria-label={`${tr('Recorrido por Chile', 'Journey through Chile')}: ${region[language]}`}
      className={compact ? 'h-8 w-3 shrink-0' : 'h-56 w-11'}
    >
      <path
        d="M20 4c5 8 1 15 5 23 3 7-2 14 1 22 3 7-5 12-2 20 2 6-5 11-4 18-1 7 5 12 2 19-3 8 3 14 1 22-2 7 4 13 1 20-4 8 2 15-1 23-3 8 2 15-2 23-2 7-5 13-6 20"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth={compact ? 5 : 3}
        className="text-ink-muted"
      />
      {!compact && (
        <>
          <path d="m13 201-4 7m14-9 5 8m-14 5-4 7m10-8 4 6" stroke="currentColor" strokeWidth="1.4" className="text-ink-muted" />
          {REGION_BANDS.map((band) => (
            <circle key={band.es} cx={band.x} cy={band.y} r="1.8" className="fill-surface-page stroke-ink-muted" />
          ))}
        </>
      )}
      <g
        style={{
          transform: `translate(${region.x}px, ${region.y}px)`,
          transition: 'transform 420ms cubic-bezier(0.2, 0.8, 0.2, 1)',
        }}
      >
        <circle r={compact ? 7 : 5.5} className="fill-ink-primary stroke-surface-page" strokeWidth="2" />
        {!compact && <circle r="9" fill="none" className="stroke-ink-primary opacity-30" />}
      </g>
    </svg>
  )
}

function scrollToSection(id: string) {
  const section = document.getElementById(id)
  if (!section) return
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  section.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
}

export default function DossierSectionNav() {
  const { language, tr } = useLanguage()
  const [activeId, setActiveId] = useState(FIRST_SECTION_ID)
  const activeIndex = Math.max(
    0,
    SECTIONS.findIndex((section) => section.id === activeId),
  )
  const activeRegion = REGION_BANDS[activeIndex] ?? REGION_BANDS[0]

  useEffect(() => {
    let frame = 0
    const update = () => {
      frame = 0
      const marker = window.innerWidth >= 1024 ? 144 : 168
      let current = FIRST_SECTION_ID
      for (const section of SECTIONS) {
        const node = document.getElementById(section.id)
        if (node && node.getBoundingClientRect().top <= marker) current = section.id
        else break
      }
      setActiveId(current)
    }
    const requestUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', requestUpdate, { passive: true })
    window.addEventListener('resize', requestUpdate)
    return () => {
      window.removeEventListener('scroll', requestUpdate)
      window.removeEventListener('resize', requestUpdate)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [])

  return (
    <>
      <div
        className="sticky top-[5.375rem] z-30 -mx-5 mb-6 border-y border-line-hairline bg-surface-page px-5 py-2 md:top-16 sm:-mx-8 sm:px-8 lg:hidden"
        style={{ backgroundColor: 'color-mix(in srgb, var(--surface-page) 92%, transparent)' }}
      >
        <div className="flex items-center gap-3">
          <ChileProgress activeIndex={activeIndex} compact />
          <span className="shrink-0 text-micro font-semibold tabular text-ink-muted" aria-hidden="true">
            {String(activeIndex + 1).padStart(2, '0')}/{String(SECTIONS.length).padStart(2, '0')}
          </span>
          <label htmlFor="dossier-section" className="sr-only">
            {tr('Sección actual', 'Current section')}
          </label>
          <select
            id="dossier-section"
            value={activeId}
            onChange={(event) => scrollToSection(event.target.value)}
            className="min-w-0 flex-1 appearance-none bg-transparent py-1 text-caption font-semibold text-ink-primary focus:outline-none"
          >
            {SECTIONS.map((section) => (
              <option key={section.id} value={section.id}>
                {section[language]}
              </option>
            ))}
          </select>
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className="h-3.5 w-3.5 shrink-0 text-ink-muted"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="m4 6 4 4 4-4" />
          </svg>
        </div>
        <span
          aria-hidden="true"
          className="absolute bottom-0 left-0 h-px bg-ink-primary transition-[width] duration-300 ease-subtle"
          style={{ width: `${((activeIndex + 1) / SECTIONS.length) * 100}%` }}
        />
      </div>

      <aside className="hidden lg:block" aria-label={tr('Índice del dossier', 'Dossier contents')}>
        <nav className="sticky top-24 grid grid-cols-[3rem_1fr] gap-2 py-2">
          <div className="flex justify-center border-r border-line-hairline pr-2 text-ink-muted">
            <ChileProgress activeIndex={activeIndex} />
          </div>
          <div>
            <p className="mb-4 pl-3 text-micro font-semibold uppercase tracking-[0.16em] text-ink-muted">
              {tr('En esta página', 'On this page')}
            </p>
            <ol>
              {SECTIONS.map((section, index) => {
                const active = section.id === activeId
                return (
                  <li key={section.id}>
                    <button
                      type="button"
                      onClick={() => scrollToSection(section.id)}
                      aria-current={active ? 'location' : undefined}
                      className={`flex w-full items-baseline gap-3 border-l px-3 py-2.5 text-left transition-colors duration-200 ease-subtle ${
                        active
                          ? 'border-ink-primary text-ink-primary'
                          : 'border-transparent text-ink-muted hover:text-ink-primary'
                      }`}
                    >
                      <span className="text-micro tabular" aria-hidden="true">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <span className="text-caption font-semibold">{section[language]}</span>
                    </button>
                  </li>
                )
              })}
            </ol>
            <p className="mt-5 pl-3 text-micro text-ink-muted">
              {activeRegion[language]} · {tr('sección', 'section')} {activeIndex + 1}/{SECTIONS.length}
            </p>
          </div>
        </nav>
      </aside>
    </>
  )
}

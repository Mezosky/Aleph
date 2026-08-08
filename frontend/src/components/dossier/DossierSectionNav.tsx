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
// Natural Earth 1:110m Admin-0 (public domain), projected into this narrow viewBox.
// A filled contour stays recognisable at sidebar size; the former centreline did not.
const CHILE_OUTLINE =
  'M33 200.5L33 213L37.6 213L40.1 213.2L38.7 215.4L35.1 217.2L33 217L30.5 216.6L27.4 214.9L23 214.1L17.6 210.9L13.3 207.9L7.4 201.6L10.9 202.8L16.9 206.5L22.5 208.5L24.7 206L26.1 202.1L30 199.8L33 200.5ZM29 3.4L31 7.3L31.6 11.3L33.8 13.7L32.5 19.1L34.8 25.4L36.5 33.2L39.5 32.4L40 33.8L38.6 39.7L33.9 42.4L34.1 51.8L33.2 53.6L34.5 55.8L31.5 59.3L28.7 64.6L27.2 69.7L27.6 75.1L25 80.9L26.9 90.6L28 91.6L28 96.8L25.6 102.3L25.7 107L22.5 110.7L22.5 115.8L23.8 121.3L21.2 123.4L20.1 128.4L19.1 134.1L19.8 141L18.1 142.1L19.1 148.6L21 150.7L19.6 153.1L21.6 154.2L22 156.3L20.2 157.4L20.6 160.7L19.1 168.1L16.8 172.9L17.3 175.8L16 179.3L12.7 181.8L13.1 187.8L14.6 189.8L17.4 189.5L17.3 193.7L19.1 196.9L29.4 197.7L33.3 198.6L29.5 198.5L27.5 199.9L23.6 201.9L22.9 207.2L21.1 207.3L16.4 205.5L11.5 201.6L6.2 198.4L4.9 194.8L6.1 191.5L3.9 187.8L3.4 178.2L5.2 172.8L9.7 168.4L3.2 166.8L7.3 161.8L8.7 152.5L13.5 154.5L15.7 142.8L12.8 141.4L11.5 148.4L8.8 147.6L10.1 139.5L11.6 129.1L13.6 125.3L12.3 119.8L12 113.5L13.8 113.3L16.4 104.2L19.3 95.2L21.1 86.8L20.1 78.4L21.4 73.8L20.9 66.9L23.4 60L24.1 49.1L25.5 37.4L26.8 24.9L26.5 15.7L25.6 7.8L27.8 6.3L29 3.4Z'
const REGION_BANDS = [
  { es: 'Norte Grande', en: 'Far North', x: 34, y: 24 },
  { es: 'Norte Chico', en: 'Near North', x: 28, y: 68 },
  { es: 'Zona Central', en: 'Central Chile', x: 23, y: 110 },
  { es: 'Zona Sur', en: 'Southern Chile', x: 20, y: 154 },
  { es: 'Zona Austral', en: 'Austral Chile', x: 22, y: 202 },
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
        d={CHILE_OUTLINE}
        fill="currentColor"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth={compact ? 2.8 : 1.2}
        className="text-ink-muted opacity-55"
      />
      {!compact && (
        <>
          {REGION_BANDS.map((band) => (
            <circle key={band.es} cx={band.x} cy={band.y} r="1.4" className="fill-surface-page stroke-ink-muted" />
          ))}
        </>
      )}
      <g
        style={{
          transform: `translate(${region.x}px, ${region.y}px)`,
          transition: 'transform 420ms cubic-bezier(0.2, 0.8, 0.2, 1)',
        }}
      >
        <circle r={compact ? 6 : 4.8} className="fill-ink-primary stroke-surface-page" strokeWidth="2" />
        {!compact && <circle r="8.5" fill="none" className="stroke-ink-primary opacity-35" />}
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
        <nav className="sticky top-24 grid grid-cols-[4rem_1fr] gap-2 py-2">
          <div className="flex justify-center border-r border-line-hairline pr-3 text-ink-muted">
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

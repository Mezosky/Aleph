/**
 * Site header: wordmark, primary navigation, theme control, skip link.
 *
 * Monochrome by design. The chrome carries no saturated colour so that when
 * colour does appear on a page it always means something about the evidence.
 * The brand mark is the single sanctioned exception — it is identity, not an
 * encoding, and it never appears inside a chart or beside a metric where its
 * hues could be mistaken for a data channel.
 */

import { NavLink } from 'react-router-dom'
import ThemeToggle from '@/components/shell/ThemeToggle'

interface NavItem {
  to: string
  label: string
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'La Megarreforma', end: true },
  { to: '/documento/18216-05', label: 'Evidencia' },
  { to: '/metodologia', label: 'Metodología' },
]

const LINK_BASE = 'whitespace-nowrap rounded-data px-2 py-1 text-caption transition-colors duration-200 ease-subtle'

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive
    ? `${LINK_BASE} text-ink-primary underline decoration-line-strong decoration-1 underline-offset-[6px]`
    : `${LINK_BASE} text-ink-secondary hover:text-ink-primary`
}

export default function Header() {
  return (
    <header
      className="sticky top-0 z-50 border-b border-line-hairline bg-surface-page backdrop-blur-md"
      style={{
        backgroundColor: 'color-mix(in srgb, var(--surface-page) 84%, transparent)',
      }}
    >
      <a
        href="#content"
        className="sr-only rounded-data focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:border focus:border-line-strong focus:bg-surface-raised focus:px-3 focus:py-2 focus:text-caption focus:text-ink-primary"
      >
        Saltar al contenido
      </a>

      <div className="mx-auto w-full max-w-shell px-5 sm:px-8">
        <div className="flex items-center justify-between gap-4 py-3 md:h-16 md:py-0">
          <NavLink to="/" aria-label="Aleph — inicio" className="group inline-flex items-center gap-2.5 rounded-data">
            <img
              src={`${import.meta.env.BASE_URL}logo-64.png`}
              alt=""
              aria-hidden="true"
              width={28}
              height={28}
              decoding="async"
              className="h-7 w-7 shrink-0 transition-transform duration-300 ease-subtle group-hover:scale-105"
            />
            <span className="text-caption font-semibold uppercase tracking-[0.22em] text-ink-primary">Aleph</span>
          </NavLink>

          <div className="flex items-center gap-2 sm:gap-4">
            <nav aria-label="Principal" className="hidden items-center gap-1 md:flex">
              {NAV_ITEMS.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <ThemeToggle />
          </div>
        </div>

        {/* Below `md` the nav moves to its own row and scrolls inside itself, so
            a narrow viewport never produces horizontal page scroll. */}
        <nav aria-label="Secciones" className="-mx-2 flex gap-1 overflow-x-auto pb-2 md:hidden">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  )
}

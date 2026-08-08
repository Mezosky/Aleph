/**
 * Theme control. Three states rather than two, because "follow the system" is a
 * real preference and a two-way switch silently destroys it the first time it
 * is pressed.
 *
 * The state is carried by an icon AND a text label (visible from `sm` up,
 * screen-reader-only below), never by colour alone.
 */

import { useTheme, type ThemeChoice } from '@/lib/theme'
import { useLanguage } from '@/i18n/LanguageContext'

const LABELS: Record<ThemeChoice, string> = {
  system: 'Sistema',
  light: 'Claro',
  dark: 'Oscuro',
}

const NEXT: Record<ThemeChoice, ThemeChoice> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
}

function Icon({ choice }: { choice: ThemeChoice }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    focusable: false,
  }

  if (choice === 'dark') {
    return (
      <svg {...common}>
        <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
      </svg>
    )
  }

  if (choice === 'light') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    )
  }

  return (
    <svg {...common}>
      <rect x="3" y="4" width="18" height="12" rx="1.5" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  )
}

export default function ThemeToggle() {
  const { language, tr } = useLanguage()
  const { choice, resolved, cycleTheme } = useTheme()
  const next = NEXT[choice]
  const labels: Record<ThemeChoice, string> =
    language === 'es' ? LABELS : { system: 'System', light: 'Light', dark: 'Dark' }

  return (
    <button
      type="button"
      onClick={cycleTheme}
      aria-label={`${tr('Tema actual', 'Current theme')}: ${labels[choice].toLowerCase()}${
        choice === 'system' ? ` (${resolved === 'dark' ? labels.dark.toLowerCase() : labels.light.toLowerCase()})` : ''
      }. ${tr('Cambiar a', 'Switch to')} ${labels[next].toLowerCase()}.`}
      title={`${tr('Tema', 'Theme')}: ${labels[choice].toLowerCase()}`}
      className="inline-flex items-center gap-1.5 rounded-data border border-line-hairline bg-surface-card px-2.5 py-1.5 text-micro uppercase tracking-wide text-ink-secondary transition-colors duration-200 ease-subtle hover:border-line-strong hover:text-ink-primary"
    >
      <Icon choice={choice} />
      <span className="sr-only sm:not-sr-only">{labels[choice]}</span>
    </button>
  )
}

/**
 * Presentation helpers. Pure functions, Intl-based, es-CL locale.
 *
 * Formatting is part of the honesty of the product: money is never printed
 * without its currency, scale and reference year, and a bipolar axis score is
 * never printed without its sign. Nothing here rounds an uncertainty away.
 */

import type { DateString, Money, MoneyUnit, Timestamp, UnitInterval } from '@/types/aleph'

export const LOCALE = 'es-CL'

/** Rendered wherever a value is genuinely absent, so a gap looks like a gap. */
export const EMPTY_MARK = '—'

/* ------------------------------------------------------------------ *
 * Numbers
 * ------------------------------------------------------------------ */

export interface NumberOptions {
  digits?: number
  minDigits?: number
  signed?: boolean
}

export function formatNumber(value: number, options: NumberOptions = {}): string {
  if (!Number.isFinite(value)) return EMPTY_MARK
  const maximumFractionDigits = options.digits ?? (Number.isInteger(value) ? 0 : 1)
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: options.minDigits ?? 0,
    maximumFractionDigits,
    signDisplay: options.signed ? 'exceptZero' : 'auto',
  }).format(value)
}

/**
 * Format a percentage. By default `value` is already expressed in percentage
 * points (`12.5` → `12,5 %`); pass `fractionOfOne` when the value is a [0,1]
 * share, which is how every `unit_interval` in the data contract is stored.
 */
export function formatPercent(
  value: number,
  options: NumberOptions & { fractionOfOne?: boolean } = {},
): string {
  if (!Number.isFinite(value)) return EMPTY_MARK
  const scaled = options.fractionOfOne ? value * 100 : value
  const digits = options.digits ?? (Number.isInteger(scaled) ? 0 : 1)
  return `${formatNumber(scaled, { ...options, digits })} %`
}

/** A [0,1] confidence as a whole-number percentage, e.g. `0.62` → `62 %`. */
export function formatConfidence(value: UnitInterval | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return EMPTY_MARK
  return formatPercent(value, { fractionOfOne: true, digits: 0 })
}

/**
 * A −100..+100 axis score. Always signed, because the sign names the pole and a
 * bare `42` would be unreadable without it. Zero prints as `0`, never `+0`.
 */
export function formatScore(value: number, options: { digits?: number } = {}): string {
  if (!Number.isFinite(value)) return EMPTY_MARK
  return new Intl.NumberFormat(LOCALE, {
    signDisplay: 'exceptZero',
    maximumFractionDigits: options.digits ?? 0,
  }).format(value)
}

/* ------------------------------------------------------------------ *
 * Money
 * ------------------------------------------------------------------ */

const MONEY_UNIT_LABELS: Record<MoneyUnit, { singular: string; plural: string }> = {
  unit: { singular: '', plural: '' },
  thousand: { singular: 'mil', plural: 'mil' },
  million: { singular: 'millón', plural: 'millones' },
  billion: { singular: 'mil millones', plural: 'mil millones' },
  percent_of_gdp: { singular: '% del PIB', plural: '% del PIB' },
}

export interface MoneyOptions {
  /** Append the reference year, e.g. `(2026)`. Default true. */
  withYear?: boolean
  /** Append the basis, e.g. `nominal`. Default false. */
  withBasis?: boolean
  digits?: number
}

/**
 * Format a `Money` object honouring currency, scale unit and reference year.
 * A bare number is never produced: an unlabelled figure cannot be compared or
 * checked, which is why the data contract forbids one in the first place.
 */
export function formatMoney(money: Money | null | undefined, options: MoneyOptions = {}): string {
  if (!money || !Number.isFinite(money.amount)) return EMPTY_MARK

  const { withYear = true, withBasis = false } = options
  const parts: string[] = []

  if (money.unit === 'percent_of_gdp') {
    parts.push(
      `${formatNumber(money.amount, { digits: options.digits ?? (Number.isInteger(money.amount) ? 0 : 1) })} % del PIB`,
    )
  } else {
    const digits = options.digits ?? (Number.isInteger(money.amount) ? 0 : 1)
    let amount: string
    try {
      amount = new Intl.NumberFormat(LOCALE, {
        style: 'currency',
        currency: money.currency,
        currencyDisplay: 'code',
        minimumFractionDigits: 0,
        maximumFractionDigits: digits,
      }).format(money.amount)
    } catch {
      // Unknown or non-ISO currency code: keep the figure legible rather than throw.
      amount = `${money.currency} ${formatNumber(money.amount, { digits })}`
    }
    const scale = MONEY_UNIT_LABELS[money.unit]
    const scaleWord = scale
      ? Math.abs(money.amount) === 1
        ? scale.singular
        : scale.plural
      : ''
    parts.push(scaleWord ? `${amount} ${scaleWord}` : amount)
  }

  const suffix: string[] = []
  if (withYear && typeof money.year === 'number') suffix.push(String(money.year))
  if (withBasis && money.basis) suffix.push(money.basis)
  if (suffix.length > 0) parts.push(`(${suffix.join(', ')})`)

  return parts.join(' ')
}

/* ------------------------------------------------------------------ *
 * Dates and times
 * ------------------------------------------------------------------ */

function toDate(value: Timestamp | DateString | Date | null | undefined): Date | null {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  // A plain `YYYY-MM-DD` is parsed as UTC midnight by the spec; anchor it to
  // midday so a negative timezone offset cannot shift the displayed day back.
  const raw = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00Z` : value
  const parsed = new Date(raw)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export type DateStyle = 'long' | 'medium' | 'short' | 'month'

const DATE_FORMATS: Record<DateStyle, Intl.DateTimeFormatOptions> = {
  long: { day: 'numeric', month: 'long', year: 'numeric' },
  medium: { day: 'numeric', month: 'short', year: 'numeric' },
  short: { day: '2-digit', month: '2-digit', year: 'numeric' },
  month: { month: 'long', year: 'numeric' },
}

export function formatDate(
  value: Timestamp | DateString | Date | null | undefined,
  style: DateStyle = 'medium',
): string {
  const date = toDate(value)
  if (!date) return EMPTY_MARK
  return new Intl.DateTimeFormat(LOCALE, DATE_FORMATS[style]).format(date)
}

export function formatDateTime(
  value: Timestamp | Date | null | undefined,
  style: DateStyle = 'medium',
): string {
  const date = toDate(value)
  if (!date) return EMPTY_MARK
  return new Intl.DateTimeFormat(LOCALE, {
    ...DATE_FORMATS[style],
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

/**
 * Relative time in Spanish: `hace 47 min`, `hace 3 h`, `hace 2 días`.
 * Short units below a day keep dense lists compact; longer spans spell the unit
 * out, because `hace 2 a` reads as noise.
 */
export function relativeTime(
  value: Timestamp | DateString | Date | null | undefined,
  now: Date = new Date(),
): string {
  const date = toDate(value)
  if (!date) return EMPTY_MARK

  const deltaMs = date.getTime() - now.getTime()
  const abs = Math.abs(deltaMs)

  if (abs < 45_000) return 'hace instantes'

  const short = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto', style: 'short' })
  const long = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto', style: 'long' })
  const sign = deltaMs < 0 ? -1 : 1

  if (abs < HOUR) return short.format(sign * Math.round(abs / MINUTE), 'minute')
  if (abs < DAY) return short.format(sign * Math.round(abs / HOUR), 'hour')
  if (abs < WEEK) return long.format(sign * Math.round(abs / DAY), 'day')
  if (abs < 30 * DAY) return long.format(sign * Math.round(abs / WEEK), 'week')
  if (abs < 365 * DAY) return long.format(sign * Math.round(abs / (30 * DAY)), 'month')
  return long.format(sign * Math.round(abs / (365 * DAY)), 'year')
}

/* ------------------------------------------------------------------ *
 * Text
 * ------------------------------------------------------------------ */

/**
 * Shorten to at most `max` characters, cutting on a word boundary when one is
 * near the limit. Returns the original string when it already fits.
 */
export function truncate(text: string, max: number, ellipsis = '…'): string {
  if (max <= 0) return ellipsis
  const clean = text.trim()
  if (clean.length <= max) return clean
  const slice = clean.slice(0, max)
  const lastSpace = slice.lastIndexOf(' ')
  const cut = lastSpace > max * 0.6 ? slice.slice(0, lastSpace) : slice
  return `${cut.replace(/[\s,.;:—-]+$/, '')}${ellipsis}`
}

/**
 * Pick the Spanish singular or plural form. When `plural` is omitted the
 * regular `-s` / `-es` rule is applied, which covers most UI nouns; pass an
 * explicit plural for anything irregular.
 */
export function pluralise(count: number, singular: string, plural?: string): string {
  if (Math.abs(count) === 1) return singular
  if (plural) return plural
  return /[aeiouáéíóú]$/i.test(singular) ? `${singular}s` : `${singular}es`
}

/** `3 afirmaciones`, `1 afirmación`, `0 afirmaciones`. */
export function countLabel(count: number, singular: string, plural?: string): string {
  return `${formatNumber(count)} ${pluralise(count, singular, plural)}`
}

/** Join a list the way Spanish does: `a, b y c`. */
export function listJoin(items: readonly string[], conjunction: 'y' | 'o' = 'y'): string {
  const values = items.filter(Boolean)
  if (values.length === 0) return ''
  if (values.length === 1) return values[0] as string
  return `${values.slice(0, -1).join(', ')} ${conjunction} ${values[values.length - 1] as string}`
}

/** First letter upper-cased, without touching the rest of the string. */
export function capitalise(text: string): string {
  return text.length === 0 ? text : text.charAt(0).toUpperCase() + text.slice(1)
}

/** A snake_case enum value rendered readably when no Spanish label exists. */
export function humaniseKey(key: string): string {
  return capitalise(key.replace(/_/g, ' '))
}

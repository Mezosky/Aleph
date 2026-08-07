/**
 * Shared visual encoding for every Aleph chart and indicator.
 *
 * The single governing rule: colour encodes EPISTEMIC STATUS — evidence
 * strength, statement type, and which pole of a policy axis an effect falls on.
 * Colour never encodes a political side. There is no red-vs-blue in this
 * product and there is no aggregate "bias" colour, because there is no
 * aggregate bias score.
 *
 * Every value below resolves to a CSS custom property defined in
 * src/styles/index.css, where the light and dark ramps were validated for
 * lightness banding, chroma, colour-vision separation, step spacing and
 * contrast. Components must import from here rather than writing a hex.
 */

import type { Polarity, StatementType, Verdict, EvidenceStrength } from '@/types/aleph'

/* ------------------------------------------------------------------ *
 * Diverging — the seven impact axes, scored -100..+100
 * ------------------------------------------------------------------ */

/**
 * Maps an axis score to a ramp step. The negative arm (teal) and the positive
 * arm (orange) are a warm/cool pair chosen specifically because it cannot be
 * read as a party colour. Near zero the ramp recedes to a neutral grey, which
 * is what "no measured tilt" should look like.
 */
export function divergingColor(score: number): string {
  const m = Math.abs(score)
  if (m < 8) return 'var(--div-mid)'
  const step = m < 30 ? 1 : m < 55 ? 2 : m < 80 ? 3 : 4
  return score < 0 ? `var(--div-neg-${step})` : `var(--div-pos-${step})`
}

/* ------------------------------------------------------------------ *
 * Sequential — framing dimensions, scored 0..100
 * ------------------------------------------------------------------ */

/**
 * Framing scores are coloured by MAGNITUDE only, never by whether the value is
 * "good". A dimension's polarity is communicated in words (see polarityNote)
 * rather than in hue, so the UI cannot imply a judgement the analysis did not
 * make — a high `loaded_language` and a high `source_diversity` are both just
 * high, and the caption says which direction is better.
 */
export function sequentialColor(score: number): string {
  const step = score < 25 ? 1 : score < 50 ? 2 : score < 75 ? 3 : 4
  return `var(--seq-${step})`
}

export function polarityNote(polarity: Polarity): string | null {
  switch (polarity) {
    case 'lower_is_better':
      return 'menor es mejor'
    case 'higher_is_better':
      return 'mayor es mejor'
    default:
      return null
  }
}

/* ------------------------------------------------------------------ *
 * Status — verdicts and evidence strength
 * ------------------------------------------------------------------ */

export interface StatusToken {
  /** CSS custom property reference. */
  color: string
  /** Always rendered alongside the colour: status is never colour-alone. */
  icon: string
  label: string
  description: string
}

/**
 * Note that `forecast_conditional` and `not_a_factual_claim` are deliberately
 * neutral-coloured. Presenting a prediction or an opinion in the same visual
 * language as a checked fact is the exact error Aleph exists to avoid.
 */
export const VERDICT_TOKENS: Record<Verdict, StatusToken> = {
  supported: {
    color: 'var(--status-good)',
    icon: '✓',
    label: 'Respaldada',
    description: 'La evidencia disponible sostiene la afirmación.',
  },
  partially_supported: {
    color: 'var(--status-warning)',
    icon: '◐',
    label: 'Parcialmente respaldada',
    description: 'Parte de la afirmación se sostiene; otra parte no, o falta contexto.',
  },
  unsupported: {
    color: 'var(--status-serious)',
    icon: '○',
    label: 'Sin respaldo',
    description: 'No se encontró evidencia que sostenga la afirmación.',
  },
  contradicted: {
    color: 'var(--status-critical)',
    icon: '✕',
    label: 'Contradicha',
    description: 'La evidencia más sólida disponible apunta en sentido contrario.',
  },
  unverifiable: {
    color: 'var(--status-neutral)',
    icon: '—',
    label: 'No verificable',
    description: 'La afirmación no puede comprobarse con la evidencia existente.',
  },
  not_a_factual_claim: {
    color: 'var(--status-neutral)',
    icon: '"',
    label: 'No es una afirmación fáctica',
    description: 'Es una opinión o un juicio de valor, no un hecho comprobable.',
  },
  forecast_conditional: {
    color: 'var(--status-neutral)',
    icon: '?',
    label: 'Proyección condicional',
    description: 'Es una predicción: sólo evaluable frente a los supuestos que asume.',
  },
}

export const STATEMENT_TOKENS: Record<StatementType, StatusToken> = {
  fact: {
    color: 'var(--status-good)',
    icon: '▪',
    label: 'Hecho',
    description: 'Afirmación verificable sobre lo que es o fue.',
  },
  interpretation: {
    color: 'var(--status-neutral)',
    icon: '◆',
    label: 'Interpretación',
    description: 'Una lectura defendible de los hechos.',
  },
  forecast: {
    color: 'var(--status-warning)',
    icon: '→',
    label: 'Proyección',
    description: 'Afirmación sobre el futuro, dependiente de supuestos.',
  },
  opinion: {
    color: 'var(--status-neutral)',
    icon: '"',
    label: 'Opinión',
    description: 'Una preferencia o valoración.',
  },
  normative: {
    color: 'var(--status-neutral)',
    icon: '§',
    label: 'Juicio normativo',
    description: 'Afirma lo que debería ser.',
  },
}

export const EVIDENCE_STRENGTH_TOKENS: Record<EvidenceStrength, StatusToken> = {
  high: {
    color: 'var(--status-good)',
    icon: '●●●',
    label: 'Alta',
    description: 'Evidencia primaria, corroborada de forma independiente.',
  },
  medium: {
    color: 'var(--status-warning)',
    icon: '●●○',
    label: 'Media',
    description: 'Evidencia razonable, con vacíos o corroboración limitada.',
  },
  low: {
    color: 'var(--status-serious)',
    icon: '●○○',
    label: 'Baja',
    description: 'Evidencia escasa o indirecta.',
  },
  insufficient: {
    color: 'var(--status-neutral)',
    icon: '○○○',
    label: 'Insuficiente',
    description: 'No hay evidencia suficiente para pronunciarse.',
  },
}

/* ------------------------------------------------------------------ *
 * Categorical — outlet identity in cross-coverage comparisons
 * ------------------------------------------------------------------ */

/**
 * Fixed order, assigned in sequence, never cycled: the slot ordering is what
 * keeps adjacent series distinguishable under colour-vision deficiency.
 *
 * Beyond eight outlets the answer is not a ninth generated hue — fold the
 * remainder into "Otros" or facet into small multiples.
 */
export const CATEGORICAL_SLOTS = [
  'var(--cat-1)',
  'var(--cat-2)',
  'var(--cat-3)',
  'var(--cat-4)',
  'var(--cat-5)',
  'var(--cat-6)',
  'var(--cat-7)',
  'var(--cat-8)',
] as const

export const MAX_CATEGORICAL_SERIES = CATEGORICAL_SLOTS.length

/**
 * Colour follows the entity, not its rank — so a filter that removes outlets
 * must not repaint the survivors. Callers pass a stable, sorted id list.
 */
export function categoricalColor(id: string, orderedIds: readonly string[]): string {
  const i = orderedIds.indexOf(id)
  return CATEGORICAL_SLOTS[i >= 0 && i < MAX_CATEGORICAL_SERIES ? i : MAX_CATEGORICAL_SERIES - 1]!
}

/* ------------------------------------------------------------------ *
 * Chart chrome
 * ------------------------------------------------------------------ */

export const CHART = {
  grid: 'var(--grid-line)',
  axis: 'var(--axis-line)',
  surface: 'var(--surface-card)',
  inkPrimary: 'var(--ink-primary)',
  inkSecondary: 'var(--ink-secondary)',
  inkMuted: 'var(--ink-muted)',
  /** 2px gap between adjacent fills, so segments never bleed together. */
  segmentGap: 2,
  /** 4px rounded data-ends, anchored at the baseline. */
  barRadius: 4,
  lineWidth: 2,
  markerSize: 8,
} as const

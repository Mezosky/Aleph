/**
 * Light/dark theme, class strategy on `<html>`.
 *
 * `index.html` runs a tiny pre-paint script that reads the same
 * `aleph-theme` key and toggles the same `dark` class before first paint, so
 * the page never flashes the wrong background. This module must stay consistent
 * with it and must not duplicate it:
 *
 *   - the stored value is `"dark"` or `"light"` and nothing else;
 *   - no stored value means "follow the operating system";
 *   - the resolved theme is expressed as the `dark` class on `documentElement`.
 */

import { useCallback, useEffect, useState } from 'react'

export const THEME_STORAGE_KEY = 'aleph-theme'

const DARK_QUERY = '(prefers-color-scheme: dark)'

/** What the user chose. `system` means nothing is stored. */
export type ThemeChoice = 'light' | 'dark' | 'system'

/** What is actually painted. */
export type ResolvedTheme = 'light' | 'dark'

function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    // Private mode or a blocked origin: fall back to following the OS.
    return null
  }
}

/** Read the persisted choice. Anything unrecognised is treated as `system`. */
export function readStoredTheme(): ThemeChoice {
  const stored = safeStorage()?.getItem(THEME_STORAGE_KEY)
  return stored === 'dark' || stored === 'light' ? stored : 'system'
}

/** Persist a choice. `system` removes the key, matching the pre-paint script. */
export function storeTheme(choice: ThemeChoice): void {
  const storage = safeStorage()
  if (!storage) return
  try {
    if (choice === 'system') storage.removeItem(THEME_STORAGE_KEY)
    else storage.setItem(THEME_STORAGE_KEY, choice)
  } catch {
    /* Quota or privacy restriction — the in-memory choice still applies. */
  }
}

/** The operating system preference right now. */
export function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

export function resolveTheme(choice: ThemeChoice, system: ResolvedTheme = systemTheme()): ResolvedTheme {
  return choice === 'system' ? system : choice
}

/** Apply a resolved theme to the document element. */
export function applyTheme(resolved: ResolvedTheme): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  document.documentElement.style.colorScheme = resolved
}

export interface ThemeApi {
  /** What the user chose, including `system`. */
  choice: ThemeChoice
  /** What is currently painted. */
  resolved: ResolvedTheme
  setTheme: (choice: ThemeChoice) => void
  /** Cycle sistema → claro → oscuro → sistema. */
  cycleTheme: () => void
  /** Flip between light and dark, leaving `system` behind. */
  toggleTheme: () => void
}

const CYCLE: readonly ThemeChoice[] = ['system', 'light', 'dark']

/**
 * Read and write the theme. Follows the OS while the choice is `system`,
 * including when the OS preference changes mid-session, and stays in step with
 * other tabs through the `storage` event.
 */
export function useTheme(): ThemeApi {
  const [choice, setChoice] = useState<ThemeChoice>(() => readStoredTheme())
  const [system, setSystem] = useState<ResolvedTheme>(() => systemTheme())

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia(DARK_QUERY)
    const onChange = (event: MediaQueryListEvent) => setSystem(event.matches ? 'dark' : 'light')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY || event.key === null) setChoice(readStoredTheme())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const resolved = resolveTheme(choice, system)

  useEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  const setTheme = useCallback((next: ThemeChoice) => {
    storeTheme(next)
    setChoice(next)
  }, [])

  const cycleTheme = useCallback(() => {
    setChoice((current) => {
      const index = CYCLE.indexOf(current)
      const next = CYCLE[(index + 1) % CYCLE.length] ?? 'system'
      storeTheme(next)
      return next
    })
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(resolved === 'dark' ? 'light' : 'dark')
  }, [resolved, setTheme])

  return { choice, resolved, setTheme, cycleTheme, toggleTheme }
}

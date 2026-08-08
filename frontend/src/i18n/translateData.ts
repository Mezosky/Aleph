export interface TranslationCatalog {
  source_language: 'es'
  target_language: 'en'
  generated_by: string
  translations: Record<string, string>
}

export function translateData<T>(value: T, catalog: TranslationCatalog | null, enabled: boolean): T {
  if (!enabled || !catalog) return value
  if (typeof value === 'string') return (catalog.translations[value] ?? value) as T
  if (Array.isArray(value)) return value.map((item) => translateData(item, catalog, true)) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, translateData(item, catalog, true)]),
    ) as T
  }
  return value
}

// Per-browser preferences. Storage can be blocked (private mode), so every access is guarded.
import type { Language } from './types'

const LANG_KEY = 'pa.language'
const LANGUAGES: readonly Language[] = ['en', 'es', 'ar']
const isLanguage = (l: string | null): l is Language => l !== null && (LANGUAGES as readonly string[]).includes(l)

export function saveLanguage(lang: Language): void {
  try {
    localStorage.setItem(LANG_KEY, lang)
  } catch { /* preference simply isn't remembered */ }
}

/** The viewer's own saved choice first (a QR link carries the laptop's language), then the link's, then English. */
export function initialLanguage(search: string): Language {
  let saved: string | null = null
  try {
    saved = localStorage.getItem(LANG_KEY)
  } catch { /* storage blocked */ }
  if (isLanguage(saved)) return saved
  const fromLink = new URLSearchParams(search).get('lang')
  return isLanguage(fromLink) ? fromLink : 'en'
}

/** The same address with `lang` set, so a reload or a shared link shows the chosen language. */
export function withLanguage(pathAndSearch: string, lang: Language): string {
  const [path, search = ''] = pathAndSearch.split('?')
  const q = new URLSearchParams(search)
  q.set('lang', lang)
  return `${path}?${q}`
}

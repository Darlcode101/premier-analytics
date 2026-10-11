// Per-browser preferences. Storage can be blocked (private mode), so every access is guarded.
import type { Language } from './types'

const KEY = 'pa.favouriteClub'

export function saveFavourite(clubId: string | null): void {
  try {
    if (clubId) localStorage.setItem(KEY, clubId)
    else localStorage.removeItem(KEY)
  } catch { /* preference simply isn't remembered */ }
}

/** The remembered favourite, if that club is playing in this match. */
export function loadFavourite(clubsInMatch: string[]): string | null {
  try {
    const id = localStorage.getItem(KEY)
    return id && clubsInMatch.includes(id) ? id : null
  } catch {
    return null
  }
}

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

// Per-browser preferences. Storage can be blocked (private mode), so every access is guarded.
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

// Substitution cards (SB-3, SB-5): which changes share a card, and whether a fan's followed player is in one.
import type { Incident } from './types'

/** Changes this close together (elapsed time) were made at the same stoppage. */
export const SAME_STOPPAGE_MS = 90_000

export function subGroups(incidents: Incident[]): Incident[][] {
  const subs = incidents.filter(i => i.kind === 'sub').sort((a, b) => a.elapsed_ms - b.elapsed_ms)
  const groups: Incident[][] = []
  for (const s of subs) {
    const last = groups[groups.length - 1]
    if (last && s.elapsed_ms - last[last.length - 1].elapsed_ms <= SAME_STOPPAGE_MS) last.push(s)
    else groups.push([s])
  }
  return groups
}

export const latestGroup = (incidents: Incident[]): Incident[] | null => subGroups(incidents).at(-1) ?? null

/** A card is known by its first change's incident id. */
export const groupKey = (groups: Incident[][], incidentId: string): string | null =>
  groups.find(g => g.some(i => i.id === incidentId))?.[0].id ?? null

export const involvesSub = (i: Incident, playerId: string | null) =>
  !!playerId && (i.player_in_id === playerId || i.player_out_id === playerId)

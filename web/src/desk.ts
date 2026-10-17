// Commentator desk helpers (CD-4..CD-13). Pure functions over the deterministic incident feed and
// live player lines, so everything here works with the AI off.
import type { Incident, Overlay, PlayerInfo, PlayerLine } from './types'

export interface Markers {
  goals: string[]      // minutes
  assists: number
  yellow: string | null
  red: string | null
  booked: boolean      // on a yellow and still on the pitch: one more and they're off
  off: string | null   // substituted off at
  on: string | null    // came on at
}

const empty = (): Markers => ({ goals: [], assists: 0, yellow: null, red: null, booked: false, off: null, on: null })

export function playerMarkers(incidents: Incident[]): Record<string, Markers> {
  const out: Record<string, Markers> = {}
  const get = (id: string) => (out[id] ??= empty())
  for (const i of incidents) {
    if (i.kind === 'goal' && i.player_id) {
      get(i.player_id).goals.push(i.minute)
      if (i.assist_id) get(i.assist_id).assists += 1
    } else if (i.kind === 'yellow' && i.player_id) {
      get(i.player_id).yellow = i.minute
    } else if ((i.kind === 'second_yellow' || i.kind === 'red') && i.player_id) {
      get(i.player_id).red = i.minute
    } else if (i.kind === 'sub') {
      if (i.player_out_id) get(i.player_out_id).off = i.minute
      if (i.player_in_id) get(i.player_in_id).on = i.minute
    }
  }
  for (const m of Object.values(out)) m.booked = m.yellow !== null && m.red === null && m.off === null
  return out
}

export const subsUsed = (incidents: Incident[], teamId: string) =>
  incidents.filter(i => i.kind === 'sub' && i.team_id === teamId).length

const LINE: Record<string, number> = { GK: 0, FB: 1, CB: 1, DM: 2, CM: 2, AM: 2, W: 3, ST: 3 }

/** The XI as goalkeeper, defence, midfield, attack, keeping the team-sheet order within each line. */
export function formationLines(xi: PlayerInfo[]): PlayerInfo[][] {
  const lines: PlayerInfo[][] = [[], [], [], []]
  for (const p of xi) lines[LINE[p.position] ?? 2].push(p)
  return lines.filter(l => l.length)
}

export const formation = (xi: PlayerInfo[]) => formationLines(xi).slice(1).map(l => l.length).join('-')

export function scorers(incidents: Incident[], teamId: string): { player_id: string; minutes: string[] }[] {
  const out: { player_id: string; minutes: string[] }[] = []
  for (const i of incidents) {
    if (i.kind !== 'goal' || i.team_id !== teamId || !i.player_id) continue
    const row = out.find(r => r.player_id === i.player_id)
    if (row) row.minutes.push(i.minute)
    else out.push({ player_id: i.player_id, minutes: [i.minute] })
  }
  return out
}

/** Spotting-board style: "C. Wolstenholme". Single names and already-short names stay as they are. */
export function boardName(name: string): string {
  const space = name.indexOf(' ')
  return space < 0 || name.length <= 14 ? name : `${name[0]}. ${name.slice(space + 1)}`
}

export const timeline = (incidents: Incident[]) => [...incidents].sort((a, b) => b.elapsed_ms - a.elapsed_ms)

export type PerformerMetric = 'xg' | 'passes_completed' | 'defensive'

export function topPerformers(players: Record<string, PlayerLine>, metric: PerformerMetric, n = 3) {
  const value = (p: PlayerLine) => (metric === 'defensive' ? p.tackles_won + p.interceptions : p[metric])
  return Object.entries(players)
    .map(([player_id, p]) => ({ player_id, value: value(p) }))
    .filter(p => p.value > 0)
    .sort((a, b) => b.value - a.value || a.player_id.localeCompare(b.player_id))
    .slice(0, n)
}

// ---------- talking points ----------


export type CardKind = 'yellow' | 'second_yellow' | 'red'

/** F-6: a team's bookings and sendings-off, in match order, for the whole match or one half. */
export function bookings(incidents: Incident[], teamId: string, period: 'match' | 'first_half' | 'second_half' = 'match') {
  return incidents
    .filter(i => (i.kind === 'yellow' || i.kind === 'second_yellow' || i.kind === 'red') && i.team_id === teamId && i.player_id)
    .filter(i => period === 'match' || i.period === (period === 'first_half' ? 1 : 2))
    .sort((a, b) => a.elapsed_ms - b.elapsed_ms)
    .map(i => ({ player_id: i.player_id as string, minute: i.minute, kind: i.kind as CardKind,
      reason: i.card_reason ?? null, victim: i.fouled_player_id ?? null }))
}

/** DK-4: is this talking point about the player in focus (its main player, or named in its facts)? */
export function involves(o: Pick<Overlay, 'player_id' | 'data'>, playerId: string | null): boolean {
  if (!playerId) return false
  return o.player_id === playerId || Object.values(o.data ?? {}).includes(playerId)
}

/** DK-4: is this incident (goal, card, substitution …) about the player in focus? */
export function incidentInvolves(i: Incident, playerId: string | null): boolean {
  if (!playerId) return false
  return [i.player_id, i.assist_id, i.player_in_id, i.player_out_id, i.fouled_player_id].includes(playerId)
}

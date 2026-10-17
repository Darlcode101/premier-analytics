// The Producer's cue on the desk (GP-1..GP-5): how long "on air" stays up, and what the cue says.
import type { State } from './state'
import type { Cue, Language } from './types'

/** GP-2: on air for the break's length at this replay speed, but never less than 6 s of real time. */
export const MIN_ON_AIR_MS = 6_000

export function onAirMs(windowS: number | null, speed: number): number {
  if (windowS === null) return Infinity  // full time: it stays up
  return Math.max((windowS * 1000) / Math.max(speed, 1), MIN_ON_AIR_MS)
}

export interface LastOnAir { ref: string; until: number; break_kind: string | null; window_s: number | null }

/** What the desk shows now: the server's state, kept on air while the last break is still being shown. */
export function shownState(cue: Cue, last: LastOnAir | null, now: number): {
  state: 'on_air' | 'up_next'; break_kind: string | null; window_s: number | null
} {
  if (cue.state === 'on_air') return { state: 'on_air', break_kind: cue.break_kind, window_s: cue.window_s }
  if (last && last.ref === cue.ref && now < last.until) return { state: 'on_air', break_kind: last.break_kind, window_s: last.window_s }
  return { state: 'up_next', break_kind: null, window_s: null }
}

/** The words for a cue, in the desk's language, from what this desk already has. */
export function cueText(cue: Cue, state: State, lang: Language): { headline: string; body: string } | null {
  if (cue.kind === 'moment') {
    const o = state.feed.find(x => x.moment_id === cue.ref)
    return o ? { headline: o.headline, body: o.body } : null
  }
  if (cue.kind === 'pattern') {
    const n = state.patterns?.notes.find(x => x.pattern_id === cue.ref) ?? state.patternAlerts.find(x => x.pattern_id === cue.ref)
    return n ? { headline: n.text, body: '' } : null
  }
  if (cue.kind === 'sub') {
    const lines = state.incidents.find(i => i.id === cue.ref)?.card?.fan[lang]
    return lines?.length ? { headline: lines[0], body: lines.slice(1).join(' ') } : null
  }
  return null
}

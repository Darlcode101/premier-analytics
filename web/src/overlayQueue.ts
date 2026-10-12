// OV-2: which graphic the lower third shows. Pure, so it can be tested without timers.
import type { Overlay } from './types'

export const SHOW_MS = 7000
export const GAP_MS = 1000

export interface ThirdState {
  current: Overlay | null
  since: number            // when it went in (or out)
  seen: Set<string>        // ids already shown
}

export const emptyThird = (): ThirdState => ({ current: null, since: 0, seen: new Set() })

/** Advance the lower third at time `now` given the feed (newest first). */
export function stepThird(s: ThirdState, feed: Overlay[], now: number): ThirdState {
  if (s.current) {
    const upgraded = feed.find(o => o.id === s.current!.id && o.version > s.current!.version)
    if (upgraded) return { ...s, current: upgraded }  // AI version replaces the instant one in place
    if (now - s.since < SHOW_MS) return s
    return { ...s, current: null, since: now }
  }
  if (now - s.since < GAP_MS) return s
  const next = feed.find(o => !s.seen.has(o.id))  // newest unseen: skip anything older
  if (!next) return s
  const seen = new Set(s.seen)
  for (const o of feed) seen.add(o.id)  // everything older than the newest counts as passed
  return { current: next, since: now, seen }
}

import type { Hello, MatchEvent, Message, Overlay, Recap, TeamStats, TraceEvent } from './types'

const TRAIL = 12
const FEED = 100
const TRACE = 200

export interface Point { x: number; y: number }
export interface TrailItem { x: number; y: number; end_x: number | null; end_y: number | null; kind: string; team_id: string | null; outcome: string | null; seq: number }

export interface State {
  status: 'idle' | 'waiting' | 'live' | 'finished'
  hello: Hello | null
  score: [number, number]
  period: number
  minute: string
  lastEvent: MatchEvent | null
  ball: Point | null
  trail: TrailItem[]
  feed: Overlay[]
  upgraded: Set<string>
  screen: Overlay[]
  stats: { home: TeamStats; away: TeamStats; chaos: number } | null
  momentum: { minute: number; value: number }[]
  trace: TraceEvent[]
  counts: { published: number; rejected: number; stale: number; error: number }
  recaps: Partial<Record<Recap['kind'], Recap>>
}

export const initialState: State = {
  status: 'idle', hello: null, score: [0, 0], period: 1, minute: '0', lastEvent: null, ball: null, trail: [],
  feed: [], upgraded: new Set(), screen: [], stats: null, momentum: [], trace: [],
  counts: { published: 0, rejected: 0, stale: 0, error: 0 }, recaps: {},
}

function mergeFeed(feed: Overlay[], incoming: Overlay[]): Overlay[] {
  const byId = new Map(feed.map(o => [o.id, o]))
  for (const o of incoming) {
    const current = byId.get(o.id)
    if (!current || o.version > current.version) byId.set(o.id, current ? { ...o, elapsed_in_ms: current.elapsed_in_ms } : o)
  }
  return [...byId.values()].sort((a, b) => b.elapsed_in_ms - a.elapsed_in_ms).slice(0, FEED)
}

export function reducer(s: State, m: Message): State {
  switch (m.type) {
    case 'hello':
      return {
        ...initialState, hello: m, status: m.status, score: [m.score_home, m.score_away],
        // keep the visual match context across profile switches
        ball: s.hello?.match_id === m.match_id ? s.ball : null,
        trail: s.hello?.match_id === m.match_id ? s.trail : [],
        momentum: s.hello?.match_id === m.match_id ? s.momentum : [],
        minute: s.hello?.match_id === m.match_id ? s.minute : '0',
      }
    case 'backfill':
      return { ...s, feed: mergeFeed(s.feed, m.overlays) }
    case 'event': {
      const next: State = {
        ...s, status: s.status === 'finished' ? 'finished' : 'live', lastEvent: m, period: m.period,
        minute: m.display_minute, score: [m.score_home, m.score_away],
      }
      if (m.x !== null && m.y !== null) {
        next.ball = m.end_x !== null && m.end_y !== null ? { x: m.end_x, y: m.end_y } : { x: m.x, y: m.y }
        next.trail = [...s.trail, {
          x: m.x, y: m.y, end_x: m.end_x, end_y: m.end_y, kind: m.kind, team_id: m.team_id, outcome: m.outcome, seq: m.seq,
        }].slice(-TRAIL)
      }
      return next
    }
    case 'stats': {
      const minute = Math.floor(m.clock_ms / 60_000)  // the second half's clock starts at 45:00
      const point = { minute, value: m.home.window.momentum }
      const momentum = s.momentum.length && s.momentum[s.momentum.length - 1].minute === minute
        ? [...s.momentum.slice(0, -1), point]
        : [...s.momentum, point]
      return { ...s, stats: { home: m.home, away: m.away, chaos: m.chaos }, momentum }
    }
    case 'overlay': {
      const upgraded = new Set(s.upgraded)
      if (m.overlay.source === 'ai') upgraded.add(m.overlay.id)
      return { ...s, feed: mergeFeed(s.feed, [m.overlay]), upgraded }
    }
    case 'screen':
      return { ...s, screen: m.overlays }
    case 'trace': {
      const counts = { ...s.counts }
      const o = m.trace.outcome
      if (o === 'published' || o === 'rejected' || o === 'stale' || o === 'error') counts[o] += 1
      return { ...s, trace: [m.trace, ...s.trace].slice(0, TRACE), counts }
    }
    case 'recap':
      return { ...s, recaps: { ...s.recaps, [m.recap.kind]: m.recap } }
    case 'end':
      return { ...s, status: 'finished', score: [m.score_home, m.score_away] }
  }
}

import type { AttackPoint, Hello, MatchEvent, Message, Overlay, Recap, TeamStats, TraceEvent } from './types'

/** Moments that get a full-screen animation in the fan app (R-8). */
export const ANIMATED = new Set(['goal', 'red_card', 'big_chance', 'woodwork', 'momentum_shift', 'half_time', 'full_time'])
const POSSESSION_EVENTS = new Set(['kickoff', 'possession_change', 'pass', 'shot'])

export interface Animation { moment_id: string; kind: string; team_id: string | null; overlay: Overlay }
export type Action = Message | { type: 'animation_done' }

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
  stats: { home: TeamStats; away: TeamStats } | null
  momentum: { minute: number; value: number }[]
  attack: AttackPoint[]
  trace: TraceEvent[]
  counts: { published: number; rejected: number; stale: number; error: number }
  recaps: Partial<Record<Recap['kind'], Recap>>
  possession: string | null
  animations: Animation[]
  animatedMoments: Set<string>
}

export const initialState: State = {
  status: 'idle', hello: null, score: [0, 0], period: 1, minute: '0', lastEvent: null, ball: null, trail: [],
  feed: [], upgraded: new Set(), screen: [], stats: null, momentum: [], attack: [], trace: [],
  counts: { published: 0, rejected: 0, stale: 0, error: 0 }, recaps: {},
  possession: null, animations: [], animatedMoments: new Set(),
}

function mergeFeed(feed: Overlay[], incoming: Overlay[]): Overlay[] {
  const byId = new Map(feed.map(o => [o.id, o]))
  for (const o of incoming) {
    const current = byId.get(o.id)
    if (!current || o.version > current.version) byId.set(o.id, current ? { ...o, elapsed_in_ms: current.elapsed_in_ms } : o)
  }
  return [...byId.values()].sort((a, b) => b.elapsed_in_ms - a.elapsed_in_ms).slice(0, FEED)
}

export function reducer(s: State, m: Action): State {
  switch (m.type) {
    case 'hello':
      return {
        ...initialState, hello: m, status: m.status, score: [m.score_home, m.score_away],
        // keep the visual match context across profile switches
        ball: s.hello?.match_id === m.match_id ? s.ball : null,
        trail: s.hello?.match_id === m.match_id ? s.trail : [],
        momentum: m.momentum ?? (s.hello?.match_id === m.match_id ? s.momentum : []),
        attack: m.attack ?? (s.hello?.match_id === m.match_id ? s.attack : []),
        minute: s.hello?.match_id === m.match_id ? s.minute : '0',
        possession: s.hello?.match_id === m.match_id ? s.possession : null,
        // moments already celebrated stay celebrated when the viewer changes profile
        animatedMoments: s.hello?.match_id === m.match_id ? s.animatedMoments : new Set(),
      }
    case 'backfill': {
      // history is shown but never animated
      const animatedMoments = new Set(s.animatedMoments)
      for (const o of m.overlays) animatedMoments.add(o.moment_id)
      return { ...s, feed: mergeFeed(s.feed, m.overlays), animatedMoments }
    }
    case 'event': {
      const next: State = {
        ...s, status: s.status === 'finished' ? 'finished' : 'live', lastEvent: m, period: m.period,
        minute: m.display_minute, score: [m.score_home, m.score_away],
        possession: POSSESSION_EVENTS.has(m.kind) && m.team_id ? m.team_id : s.possession,
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
      const minute = Math.floor((m.elapsed_ms ?? m.clock_ms) / 60_000)  // elapsed: stoppage time never collides
      const point = { minute, value: m.home.window.momentum }
      const momentum = s.momentum.length && s.momentum[s.momentum.length - 1].minute === minute
        ? [...s.momentum.slice(0, -1), point]
        : [...s.momentum, point]
      let attack = s.attack
      if (m.attack) {
        const p = m.attack
        attack = [...s.attack.filter(a => a.minute !== p.minute), p].sort((a, b) => a.minute - b.minute)
      }
      return { ...s, stats: { home: m.home, away: m.away }, momentum, attack }
    }
    case 'overlay': {
      const o = m.overlay
      const upgraded = new Set(s.upgraded)
      if (o.source === 'ai') upgraded.add(o.id)
      let { animations, animatedMoments } = s
      if (ANIMATED.has(o.kind) && !animatedMoments.has(o.moment_id)) {
        animatedMoments = new Set(animatedMoments).add(o.moment_id)
        animations = [...animations, { moment_id: o.moment_id, kind: o.kind, team_id: o.team_id, overlay: o }]
      }
      return { ...s, feed: mergeFeed(s.feed, [o]), upgraded, animations, animatedMoments }
    }
    case 'animation_done':
      return { ...s, animations: s.animations.slice(1) }
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

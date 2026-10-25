import type { AttackPoint, Brief, ContextCard, Cue, FactFlag, FactResult, Hello, Storyline, PatternNote, PatternsUpdate, TeamShape, Incident, MatchEvent, Message, Overlay, PlayerLine, Recap, TeamStats, TraceEvent } from './types'

const POSSESSION_EVENTS = new Set(['kickoff', 'possession_change', 'pass', 'shot'])

/** A line the desk said or typed, shown at once and filled in when its check comes back (FC-2, 10-25). */
export interface SaidLine { id: string; line: string; status: 'checking' | 'done' | 'unavailable' | 'error'; results: FactResult[] }
export type Action = Message | { type: 'said_local'; id: string; line: string }

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
  incidents: Incident[]
  players: Record<string, PlayerLine>
  contexts: ContextCard[]
  clockMs: number  // match clock from the latest event or stats
  patterns: PatternsUpdate | null
  patternAlerts: (PatternNote & { minute: string; elapsed_ms: number })[]
  shape: { home: TeamShape; away: TeamShape } | null
  cue: Cue | null              // GP-1: the Producer's current cue (desk only)
  cueNote: { ref: string; text: string } | null  // GP-5: belongs to the talking point, not one cue
  used: Set<string>            // GP-4: talking points used, shared by every desk on the match
  brief: Brief | null          // PS-1
  storylines: Storyline[]      // PS-2, PS-3: shared by every desk on the match
  storylineError: string | null
  factFlags: FactFlag[]          // FC-2: this desk's flags, newest first (never stored server-side)
  factChecked: number
  factStatus: 'ok' | 'unavailable' | 'error' | null
  factLog: SaidLine[]            // newest first, a handful kept
}

export const initialState: State = {
  status: 'idle', hello: null, score: [0, 0], period: 1, minute: '0', lastEvent: null, ball: null, trail: [],
  feed: [], upgraded: new Set(), screen: [], stats: null, momentum: [], attack: [], trace: [],
  counts: { published: 0, rejected: 0, stale: 0, error: 0 }, recaps: {},
  possession: null, incidents: [], players: {}, contexts: [], clockMs: 0, patterns: null, patternAlerts: [], shape: null,
  cue: null, cueNote: null, used: new Set(), brief: null, storylines: [], storylineError: null,
  factFlags: [], factChecked: 0, factStatus: null, factLog: [],
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
        clockMs: s.hello?.match_id === m.match_id ? s.clockMs : 0,
        period: s.hello?.match_id === m.match_id ? s.period : 1,
        possession: s.hello?.match_id === m.match_id ? s.possession : null,
        incidents: m.incidents ?? [],
        contexts: m.context ?? [],
        recaps: Object.fromEntries((m.recaps ?? []).map(r => [r.kind, r])),
        trace: m.trace ?? [],
        counts: m.trace_counts ?? initialState.counts,
        patterns: m.patterns ?? null,
        patternAlerts: s.hello?.match_id === m.match_id ? s.patternAlerts : [],
        shape: s.hello?.match_id === m.match_id ? s.shape : null,
        players: s.hello?.match_id === m.match_id ? s.players : {},
        cue: m.cue ?? null,
        cueNote: m.cue && m.cue_note ? { ref: m.cue.ref, text: m.cue_note } : null,
        used: new Set(m.used ?? []),
        brief: m.brief ?? null,
        storylines: m.storylines ?? [],
      }
    case 'backfill': {
      return { ...s, feed: mergeFeed(s.feed, m.overlays) }
    }
    case 'event': {
      const next: State = {
        ...s, status: s.status === 'finished' ? 'finished' : 'live', lastEvent: m, period: m.period,
        minute: m.display_minute, score: [m.score_home, m.score_away], clockMs: Math.max(s.period === m.period ? s.clockMs : 0, m.clock_ms),
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
      return { ...s, stats: { home: m.home, away: m.away }, momentum, attack, players: m.players ?? s.players,
        clockMs: m.period === s.period ? Math.max(s.clockMs, m.clock_ms) : s.clockMs, shape: m.shape ?? s.shape }
    }
    case 'overlay': {
      const o = m.overlay
      const upgraded = new Set(s.upgraded)
      if (o.source === 'ai') upgraded.add(o.id)
      return { ...s, feed: mergeFeed(s.feed, [o]), upgraded }
    }
    case 'screen':
      return { ...s, screen: m.overlays }
    case 'trace': {
      const counts = { ...s.counts }
      const o = m.trace.outcome
      if (o === 'published' || o === 'rejected' || o === 'stale' || o === 'error') counts[o] += 1
      return { ...s, trace: [m.trace, ...s.trace].slice(0, TRACE), counts }
    }
    case 'incident':
      return s.incidents.some(i => i.id === m.incident.id) ? s : { ...s, incidents: [...s.incidents, m.incident] }
    case 'patterns': {
      // PA-6: alerted patterns become talking points (once each).
      const known = new Set(s.patternAlerts.map(a => a.pattern_id))
      const fresh = m.notes.filter(n => m.alerts.includes(n.pattern_id) && !known.has(n.pattern_id))
        .map(n => ({ ...n, minute: m.minute, elapsed_ms: m.elapsed_ms }))
      return { ...s, patterns: m, patternAlerts: fresh.length ? [...s.patternAlerts, ...fresh] : s.patternAlerts }
    }
    case 'context': {
      const c = m.context
      const known = s.contexts.some(x => x.moment_id === c.moment_id && x.language === c.language)
      return known ? s : { ...s, contexts: [...s.contexts, c] }
    }
    case 'cue':
      return { ...s, cue: m.cue, cueNote: s.cueNote && m.cue && s.cueNote.ref === m.cue.ref ? s.cueNote : null }
    case 'cue_note':
      return s.cue && s.cue.ref === m.ref ? { ...s, cueNote: { ref: m.ref, text: m.text } } : s
    case 'used': {
      const used = new Set(s.used)
      if (m.used) used.add(m.ref)
      else used.delete(m.ref)
      return { ...s, used }
    }
    case 'brief':
      return { ...s, brief: m.brief }
    case 'storylines':
      return { ...s, storylines: m.storylines, storylineError: null }
    case 'storyline_error':
      return { ...s, storylineError: m.error }
    case 'said_local':
      return { ...s, factLog: [{ id: m.id, line: m.line, status: 'checking' as const, results: [] }, ...s.factLog].slice(0, 6) }
    case 'fact_check': {
      const factLog = s.factLog.map(l => l.id === m.id
        ? { ...l, status: m.status === 'ok' ? 'done' as const : m.status, results: m.results ?? [] } : l)
      return { ...s, factFlags: [...m.flags, ...s.factFlags].slice(0, 10), factChecked: s.factChecked + m.checked, factStatus: m.status, factLog }
    }
    case 'recap':
      return { ...s, recaps: { ...s.recaps, [m.recap.kind]: m.recap } }
    case 'end':
      return { ...s, status: 'finished', score: [m.score_home, m.score_away] }
  }
}

// Wire format from the backend (src/premier_analytics/app.py). Keep in sync.

export type Language = 'en' | 'es' | 'ar'
export type Mode = 'fan' | 'analyst'

export interface Profile {
  mode: Mode
  language: Language
  club_id: string | null
  player_id: string | null
}

export interface PlayerInfo {
  id: string
  name: string
  number: number
  position: string
}

export interface ClubInfo {
  id: string
  name: string
  short_name: string
  colors: [string, string]
  lineup: PlayerInfo[]
  bench: PlayerInfo[]
}

export interface Overlay {
  id: string
  match_id: string
  moment_id: string
  audience: string
  kind: string
  team_id: string | null
  player_id?: string | null
  priority: number
  slot: 'lower_third' | 'corner' | 'ticker'
  clock_in_ms: number
  clock_out_ms: number
  minute: string
  elapsed_in_ms: number
  headline: string
  body: string
  language: Language
  direction: 'ltr' | 'rtl'
  source: 'template' | 'ai'
  version: number
  evidence: string[]
  data: Record<string, string | number | boolean>
  model: string | null
}

export interface WindowStats {
  momentum: number
  field_tilt: number
  ppda: number | null
  tempo: number
  shots: number
  xg: number
}

export interface TeamStats {
  goals: number
  shots: number
  shots_on_target: number
  big_chances: number
  xg: number
  passes: number
  passes_completed: number
  final_third_passes: number
  pass_accuracy: number
  possession_pct: number
  tackles_won: number
  interceptions: number
  fouls: number
  yellow_cards: number
  red_cards: number
  corners?: number
  window: WindowStats
  last10?: LastWindow
  first_half?: LastWindow
  second_half?: LastWindow | null
}

/** Team figures over the last 10 minutes of play (CD-11). */
export type LastWindow = Pick<TeamStats, 'goals' | 'shots' | 'shots_on_target' | 'big_chances' | 'xg' | 'passes'
  | 'passes_completed' | 'final_third_passes' | 'pass_accuracy' | 'possession_pct' | 'tackles_won' | 'interceptions' | 'fouls'
  | 'yellow_cards' | 'red_cards' | 'corners'>

export interface PlayerLine {
  passes: number
  passes_completed: number
  shots: number
  goals: number
  assists: number
  xg: number
  tackles_won: number
  interceptions: number
  fouls: number
  yellow_cards: number
  red_cards: number
}

/** One line of the match timeline, built from events, never from AI (CD-8). */
export interface Incident {
  id: string
  event_id: string
  kind: 'goal' | 'yellow' | 'second_yellow' | 'red' | 'sub' | 'big_chance' | 'woodwork' | 'penalty'
  minute: string
  elapsed_ms: number
  period: number
  team_id: string | null
  player_id: string | null
  assist_id?: string | null
  score_home?: number
  score_away?: number
  player_in_id?: string
  player_out_id?: string
  xg?: number
  outcome?: string
  set_piece?: 'corner' | 'penalty' | null
}

export interface SourceLink { url: string; title: string }

/** Real-world context beside a moment (CX-2): a benchmark or tactics explainer with its sources. */
export interface ContextCard {
  moment_id: string
  minute: string
  language: Language
  text: string
  entry_id: string
  topic: string
  kind: 'benchmark' | 'tactic'
  sources: SourceLink[]
  origin: string
}

export interface Explainer { topic: string; text: string; sources: SourceLink[] }

export interface AskResult {
  status: 'ok' | 'cached' | 'limit' | 'timeout' | 'off_topic' | 'no_source' | 'error' | 'unavailable'
  text: string
  sources: SourceLink[]
  remaining: number
}

/** Pattern Analyst (PA-*): one note about how a team is playing. scope 'season' = what they're known for. */
export interface PatternNote {
  pattern_id: string
  team_id: string
  kind: 'flank' | 'switch' | 'high_regains' | 'long_shots' | 'hub' | 'counters' | 'unusual' | 'playmaker'
  scope: 'match' | 'second_half' | 'season'
  value: string
  text: string
  numbers: Record<string, number | string>
  source: 'ai' | 'plain'
}

export interface PatternsUpdate {
  minute: string
  elapsed_ms: number
  language: Language
  notes: PatternNote[]
  alerts: string[]
  fan_lines: Record<string, string>
}

/** Raw counts behind the pattern pictures, per team in its own attacking frame. */
export interface TeamShape {
  entries: Record<'left' | 'centre' | 'right', number>
  regains: Record<'defensive' | 'middle' | 'attacking', number>
  shots: { x: number; y: number; counter: boolean }[]
}

export interface ClubSeason {
  position: number
  played: number
  won: number
  drawn: number
  lost: number
  goals_for: number
  goals_against: number
  points: number
  form: ('W' | 'D' | 'L')[]
  players: Record<string, { goals: number; assists: number }>
  top_scorers: { player_id: string; goals: number }[]
}

export interface SeasonContext {
  matches: number
  table: { club_id: string; short_name: string; position: number; played: number; points: number; goal_difference: number }[]
  home: ClubSeason
  away: ClubSeason
}

export interface TraceEvent {
  moment_id: string
  audience: string
  agent: string
  outcome: 'ok' | 'rejected' | 'error' | 'stale' | 'published'
  model: string | null
  ms: number
  detail: string
}

export interface Recap {
  headline: string
  summary: string
  key_points: string[]
  language: Language
  kind: 'half_time' | 'full_time'
  model: string | null
}

export interface AttackCounts { shots: number; xg: number; final_third_passes: number; high_regains: number }
export interface AttackPoint {
  minute: number
  value: number          // -1..1, > 0 = home on top
  window: [number, number]
  label: string          // broadcast clock, e.g. "45+2"
  home: AttackCounts
  away: AttackCounts
}

export type Message =
  | {
      type: 'hello'
      match_id: string
      status: 'waiting' | 'live' | 'finished'
      speed: number
      audience: string
      home: ClubInfo
      away: ClubInfo
      venue: string
      referee: string
      kickoff: string
      weather: { condition: string; temp_c: number }
      score_home: number
      score_away: number
      momentum?: { minute: number; value: number }[]
      attack?: AttackPoint[]
      incidents?: Incident[]
      subs_allowed?: number
      season?: SeasonContext | null
      context?: ContextCard[]
      explainers?: Record<string, Explainer>
      patterns?: (PatternsUpdate & { type: 'patterns' }) | null
      recaps?: Recap[]
      trace?: TraceEvent[]
      trace_counts?: { published: number; rejected: number; stale: number; error: number }
    }
  | { type: 'backfill'; overlays: Overlay[] }
  | {
      type: 'event'
      kind: string
      seq: number
      period: number
      clock_ms: number
      display_minute: string
      team_id: string | null
      player_id: string | null
      player: string | null
      outcome: string | null
      score_home: number
      score_away: number
      x: number | null
      y: number | null
      end_x: number | null
      end_y: number | null
    }
  | { type: 'patterns' } & PatternsUpdate
  | { type: 'stats'; home: TeamStats; away: TeamStats; players?: Record<string, PlayerLine>; shape?: { home: TeamShape; away: TeamShape }; chaos: number; clock_ms: number; period: number; elapsed_ms?: number; attack?: AttackPoint }
  | { type: 'incident'; incident: Incident }
  | { type: 'context'; context: ContextCard }
  | { type: 'overlay'; overlay: Overlay }
  | { type: 'screen'; overlays: Overlay[] }
  | { type: 'trace'; trace: TraceEvent }
  | { type: 'recap'; recap: Recap }
  | { type: 'end'; score_home: number; score_away: number }

export type Hello = Extract<Message, { type: 'hello' }>
export type MatchEvent = Extract<Message, { type: 'event' }>

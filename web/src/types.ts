// Wire format from the backend (src/premier_analytics/app.py). Keep in sync.

export type { Language } from './languages'
import type { Language } from './languages'
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
  card?: SubCard  // SB-1: substitutions only
  card_reason?: string | null  // F-6b: cards only
  fouled_player_id?: string | null
}

/** SB-1, SB-4: built from match facts on the server, never by AI. */
export interface SubCard {
  event_id: string
  team_id: string
  minute: string
  elapsed_ms: number
  score_home: number
  score_away: number
  subs_used: number
  subs_allowed: number
  change: 'like_for_like' | 'more_attacking' | 'more_defensive'
  off: {
    player_id: string; number: number; position: string; minutes: number; booked: boolean
    line: Omit<PlayerLine, 'yellow_cards' | 'red_cards'>
    season: { goals: number; assists: number } | null
  }
  on: { player_id: string; number: number; position: string; season: { goals: number; assists: number } | null }
  fan: Record<Language, string[]>
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
  status: 'ok' | 'cached' | 'limit' | 'timeout' | 'off_topic' | 'no_source' | 'error' | 'unavailable' | 'not_in_data' | 'facts_only'
  text: string
  sources: SourceLink[]
  remaining: number
  source?: 'match'             // AM-1: answered from this match's tools (web answers have no source field)
  evidence?: { tool: string; args: Record<string, unknown>; summary: string }[]
  as_of?: string
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
      cue?: Cue | null
      brief?: Brief | null
      storylines?: Storyline[]
      cue_note?: string | null
      used?: string[]
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
  | { type: 'cue'; cue: Cue | null }
  | { type: 'cue_note'; ref: string; language: Language; text: string }
  | { type: 'used'; ref: string; used: boolean }
  | { type: 'brief'; brief: Brief }
  | { type: 'storylines'; storylines: Storyline[] }
  | { type: 'storyline_error'; error: string }
  | { type: 'fact_check'; id?: string | null; checked: number; flags: FactFlag[]; results?: FactResult[]; status: 'ok' | 'unavailable' | 'error' }
  | { type: 'context'; context: ContextCard }
  | { type: 'overlay'; overlay: Overlay }
  | { type: 'screen'; overlays: Overlay[] }
  | { type: 'trace'; trace: TraceEvent }
  | { type: 'recap'; recap: Recap }
  | { type: 'end'; score_home: number; score_away: number }

export type Hello = Extract<Message, { type: 'hello' }>
export type MatchEvent = Extract<Message, { type: 'event' }>

/** GP-1..GP-5: the Producer's cue — what to say next, and whether now is a break to say it in. */
export interface Cue {
  id: number
  ref: string            // moment id, pattern id or incident id
  kind: 'moment' | 'pattern' | 'sub' | 'storyline' | 'fact'
  label: string
  source: string         // the agent it came from
  team_id: string | null
  minute: string
  reasons: string[]
  state: 'on_air' | 'up_next'
  break_kind: string | null
  window_s: number | null
  storyline?: string | null  // PS-3: the storyline (English text) this point feeds
}

/** PS-1: the pre-match brief (the table and form are in the season context). */
export interface BriefSide {
  players_to_watch: { player_id: string; why: 'top_scorer' | 'top_assists' | 'playmaker'; value: number }[]
  styles: { kind: string; value: string; share: number; league: number | null }[]
}
export interface StorylineSuggestion {
  seed_id: string; kind: string; text: Record<Language, string>; players: string[]; clubs: string[]; source: 'ai' | 'plain'
}
export interface Brief {
  meetings: { matchday: number; home: string; away: string; home_goals: number; away_goals: number }[]
  home: BriefSide
  away: BriefSide
  suggestions: StorylineSuggestion[]
}
/** PS-2, PS-3: a storyline the desk follows, with the Watcher's updates. */
export interface Storyline {
  id: string; text: Record<Language, string>; players: string[]; clubs: string[]; source: 'suggested' | 'custom'
  seed_id: string | null
  updates: { ref: string; minute: string; text: Record<Language, string>; source: 'ai' | 'plain' }[]
}

/** FC-2: a clear error in something the commentator said, with the right number and where it came from. */
export interface FactFlag {
  verdict: 'wrong'; subject: string; metric: string; claimed: number; actual: number; since_minute: number | null
  quote: string; evidence: string; text: Record<Language, string>
}

/** FC-2 (10-25): every checked claim, right or wrong, so the desk can show it responded. */
export interface FactResult { verdict: 'correct' | 'wrong'; text: Record<Language, string> }

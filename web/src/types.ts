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
  pass_accuracy: number
  possession_pct: number
  tackles_won: number
  interceptions: number
  fouls: number
  yellow_cards: number
  red_cards: number
  window: WindowStats
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
  | { type: 'stats'; home: TeamStats; away: TeamStats; chaos: number; clock_ms: number; period: number; elapsed_ms?: number }
  | { type: 'overlay'; overlay: Overlay }
  | { type: 'screen'; overlays: Overlay[] }
  | { type: 'trace'; trace: TraceEvent }
  | { type: 'recap'; recap: Recap }
  | { type: 'end'; score_home: number; score_away: number }

export type Hello = Extract<Message, { type: 'hello' }>
export type MatchEvent = Extract<Message, { type: 'event' }>

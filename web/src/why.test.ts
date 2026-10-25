import { describe, expect, it } from 'vitest'
import { odds, whyLines } from './why'
import type { Language, Overlay } from './types'
import { LANGUAGES } from './languages'

const names = { har: 'Hyperion', ngc: 'Selene', p9: 'Ezra Jovanovic', p20: 'Kai Greaves' }
const ov = (kind: string, data: Overlay['data'], extra: Partial<Overlay> = {}): Overlay => ({
  id: 'o', match_id: 'm', moment_id: 'mo', audience: 'fan.en.-.-', kind, team_id: 'har', player_id: 'p9', priority: 0.5,
  slot: 'lower_third', clock_in_ms: 0, clock_out_ms: 1, minute: '23', elapsed_in_ms: 0, headline: 'h', body: 'b',
  language: 'en', direction: 'ltr', source: 'template', version: 1, evidence: [], data, model: null, ...extra,
})
const why = (o: Overlay, lang: Language = 'en') => whyLines(o, names, 'har', 'ngc', lang)

const ALL: Overlay[] = [
  ov('goal', { score_home: 1, score_away: 0, goal_context: 'takes_lead', shot_xg: 0.12, shot_distance_m: 17.6 }),
  ov('goal', { score_home: 1, score_away: 1, goal_context: 'equaliser', set_piece: 'penalty', shot_xg: 0.78, shot_distance_m: 11 }),
  ov('big_chance', { shot_xg: 0.45, shot_distance_m: 8.2, outcome: 'saved', score_home_if_scored: 2, score_away_if_scored: 1 }),
  ov('woodwork', { shot_xg: 0.05, shot_distance_m: 24, outcome: 'woodwork' }),
  ov('shot_on_target', { shot_xg: 0.09, shot_distance_m: 21, outcome: 'saved', score_home_if_scored: 1, score_away_if_scored: 0 }),
  ov('rocket_shot', { shot_speed_kmh: 117.4, shot_xg: 0.04, shot_distance_m: 27, outcome: 'saved' }),
  ov('penalty', { taker: 'p9' }),
  ov('milestone', { player_goals: 2, milestone: 'brace' }),
  ov('yellow_card', { card: 'yellow', card_reason: 'late_tackle', fouled_player: 'p20' }),
  ov('red_card', { card: 'red', card_reason: 'violent_conduct', players_remaining: 10 }),
  ov('great_pass', { pass_difficulty: 0.81, pass_distance_m: 38.4 }),
  ov('momentum_shift', { field_tilt: 0.71, window_shots: 4, window_xg: 0.6, window_minutes: 10 }),
  ov('pressure_spell', { field_tilt: 0.8, window_shots: 3, window_minutes: 10, goals_in_spell: 1 }),
  ov('half_time', { score_home: 0, score_away: 0, possession_home_pct: 58.2, shots_home: 7, shots_away: 3, xg_home: 1.1, xg_away: 0.3 }, { team_id: null, player_id: null }),
]

describe('plain-words Why? (F-7)', () => {
  it('turns xG into everyday odds', () => {
    expect(odds(0.12)).toEqual({ n: 1, outOf: 8 })
    expect(odds(0.45)).toEqual({ n: 1, outOf: 2 })
    expect(odds(0.78)).toEqual({ n: 8, outOf: 10 })
    expect(odds(0.001).outOf).toBe(100)
  })
  it('explains a goal by what it does to the game and how hard the chance was', () => {
    expect(why(ALL[0])).toEqual(['It puts Hyperion ahead.', 'From 18 m out, chances like this go in about 1 time in 8.'])
    expect(why(ALL[1])).toEqual(['It levels the game at 1-1.', 'It came from the penalty spot.'])
  })
  it('says what a missed chance would have meant', () => {
    expect(why(ALL[2])).toEqual(['From 8 m out, chances like this go in about 1 time in 2.', 'A goal would have made it 2-1.'])
  })
  it('explains cards and pressure without jargon', () => {
    expect(why(ALL[8])).toEqual(['Late tackle on Kai Greaves.', 'Ezra Jovanovic is on a yellow: another one means a red card.'])
    expect(why(ALL[9])).toEqual(['Violent conduct.', 'Hyperion play the rest of the match with 10 players.'])
    expect(why(ALL[12])).toEqual([
      'Hyperion had 3 shots in the last 10 minutes.',
      "Most of the play was in Selene's half, so Hyperion kept them pinned back.",
      'They scored 1 goal in that spell.',
    ])
  })
  it.each(LANGUAGES)('every kind has 1-3 clean sentences in %s', lang => {
    for (const o of ALL) {
      const lines = why(o, lang)
      expect(lines.length, o.kind).toBeGreaterThanOrEqual(1)
      expect(lines.length).toBeLessThanOrEqual(3)
      const text = lines.join(' ')
      expect(text).not.toMatch(/undefined|NaN|\{|xG|%/)
    }
  })
  it('never shows a number the facts do not support', () => {
    for (const o of ALL) {
      const allowed = new Set<string>()
      for (const v of Object.values(o.data)) if (typeof v === 'number') {
        allowed.add(String(v)); allowed.add(String(Math.round(v)))
        const { n, outOf } = odds(v); allowed.add(String(n)); allowed.add(String(outOf))
      }
      for (const n of ['8', '10']) allowed.add(n)  // penalty odds
      for (const lang of LANGUAGES) {
        for (const m of why(o, lang).join(' ').match(/\d+/g) ?? []) expect(allowed, `${lang} ${o.kind}: ${m}`).toContain(m)
      }
    }
  })
})

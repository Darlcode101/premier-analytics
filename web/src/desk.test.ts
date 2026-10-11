import { beforeEach, describe, expect, it } from 'vitest'
import {
  boardName, formation, formationLines, loadUsed, playerMarkers, saveUsed, scorers, subsUsed, timeline, topOpenPoint, topPerformers,
} from './desk'
import { initialState, reducer } from './state'
import type { Hello, Incident, Overlay, PlayerInfo, PlayerLine } from './types'

let n = 0
const inc = (kind: Incident['kind'], extra: Partial<Incident> = {}): Incident => {
  n += 1
  return { id: `i${n}`, event_id: `e${n}`, kind, minute: '10', elapsed_ms: n * 60_000, period: 1, team_id: 'har', player_id: 'p1', ...extra }
}
const player = (id: string, position: string, number = 1): PlayerInfo => ({ id, name: id, number, position })

describe('line-up markers (CD-5, CD-7)', () => {
  it('counts goals and assists and flags bookings', () => {
    const m = playerMarkers([
      inc('goal', { player_id: 'p9', assist_id: 'p7', minute: '23' }),
      inc('goal', { player_id: 'p9', minute: '67' }),
      inc('yellow', { player_id: 'p4', minute: '30' }),
    ])
    expect(m.p9.goals).toEqual(['23', '67'])
    expect(m.p7.assists).toBe(1)
    expect(m.p4.yellow).toBe('30')
    expect(m.p4.booked).toBe(true)
  })
  it('a second yellow is a sending-off, not a booking', () => {
    const m = playerMarkers([inc('yellow', { player_id: 'p4', minute: '30' }), inc('second_yellow', { player_id: 'p4', minute: '71' })])
    expect(m.p4.red).toBe('71')
    expect(m.p4.booked).toBe(false)
  })
  it('records substitutions on both players and counts them per team', () => {
    const incs = [
      inc('sub', { player_id: 'p20', player_in_id: 'p20', player_out_id: 'p8', minute: '60' }),
      inc('sub', { team_id: 'ngc', player_id: 'q20', player_in_id: 'q20', player_out_id: 'q8', minute: '65' }),
      inc('sub', { player_id: 'p21', player_in_id: 'p21', player_out_id: 'p9', minute: '75' }),
    ]
    const m = playerMarkers(incs)
    expect(m.p8.off).toBe('60')
    expect(m.p20.on).toBe('60')
    expect(subsUsed(incs, 'har')).toBe(2)
    expect(subsUsed(incs, 'ngc')).toBe(1)
  })
})

describe('formation (CD-5)', () => {
  const xi = [player('gk', 'GK'), player('rb', 'FB'), player('cb1', 'CB'), player('cb2', 'CB'), player('lb', 'FB'),
    player('dm', 'DM'), player('cm1', 'CM'), player('cm2', 'CM'), player('rw', 'W'), player('st', 'ST'), player('lw', 'W')]
  it('groups the XI into goalkeeper, defence, midfield and attack', () => {
    expect(formationLines(xi).map(l => l.map(p => p.id))).toEqual([
      ['gk'], ['rb', 'cb1', 'cb2', 'lb'], ['dm', 'cm1', 'cm2'], ['rw', 'st', 'lw']])
    expect(formation(xi)).toBe('4-3-3')
  })
})

describe('header scorers (CD-4)', () => {
  it('lists each scorer once with all their minutes, in order', () => {
    const incs = [inc('goal', { player_id: 'a', minute: '12' }), inc('goal', { team_id: 'ngc', player_id: 'b', minute: '30' }),
      inc('goal', { player_id: 'a', minute: '45+1' }), inc('goal', { player_id: 'c', minute: '80' })]
    expect(scorers(incs, 'har')).toEqual([{ player_id: 'a', minutes: ['12', '45+1'] }, { player_id: 'c', minutes: ['80'] }])
    expect(scorers(incs, 'ngc')).toEqual([{ player_id: 'b', minutes: ['30'] }])
  })
})

describe('timeline (CD-8)', () => {
  it('is newest first and keeps every incident once', () => {
    const a = inc('goal'), b = inc('yellow'), c = inc('sub', { player_in_id: 'x', player_out_id: 'y' })
    expect(timeline([a, b, c]).map(i => i.id)).toEqual([c.id, b.id, a.id])
  })
  it('the reducer keeps incidents from hello and ignores duplicates', () => {
    const a = inc('goal')
    const hello = { type: 'hello' as const, match_id: 'm', status: 'live' as const, speed: 1, audience: 'x', home: {} as never, away: {} as never,
      venue: '', referee: '', kickoff: '', weather: { condition: 'clear', temp_c: 10 }, score_home: 1, score_away: 0, incidents: [a] } satisfies Hello
    let s = reducer(initialState, hello)
    s = reducer(s, { type: 'incident', incident: a })
    s = reducer(s, { type: 'incident', incident: inc('yellow') })
    expect(s.incidents).toHaveLength(2)
  })
})

describe('top performers (CD-13)', () => {
  const line = (p: Partial<PlayerLine>): PlayerLine => ({ passes: 0, passes_completed: 0, shots: 0, goals: 0, assists: 0, xg: 0,
    tackles_won: 0, interceptions: 0, fouls: 0, yellow_cards: 0, red_cards: 0, ...p })
  const players = { a: line({ xg: 0.8, passes_completed: 20, tackles_won: 1 }), b: line({ xg: 0.3, passes_completed: 40, interceptions: 5 }),
    c: line({ xg: 0.3, passes_completed: 10, tackles_won: 2, interceptions: 2 }), d: line({}) }
  it('ranks by metric, breaks ties by id, leaves out zeros', () => {
    expect(topPerformers(players, 'xg').map(p => p.player_id)).toEqual(['a', 'b', 'c'])
    expect(topPerformers(players, 'passes_completed', 2).map(p => p.player_id)).toEqual(['b', 'a'])
    expect(topPerformers(players, 'defensive').map(p => [p.player_id, p.value])).toEqual([['b', 5], ['c', 4], ['a', 1]])
  })
})

describe('talking points (CD-9, CD-10)', () => {
  const store = new Map<string, string>()
  beforeEach(() => {
    store.clear()
    ;(globalThis as Record<string, unknown>).localStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    }
  })
  it('used points are remembered per match', () => {
    saveUsed('m1', new Set(['o1', 'o2']))
    expect(loadUsed('m1')).toEqual(new Set(['o1', 'o2']))
    expect(loadUsed('m2')).toEqual(new Set())
  })
  it('never throws when storage is blocked', () => {
    ;(globalThis as Record<string, unknown>).localStorage = { getItem: () => { throw new Error('x') }, setItem: () => { throw new Error('x') } }
    expect(() => saveUsed('m1', new Set(['o1']))).not.toThrow()
    expect(loadUsed('m1')).toEqual(new Set())
  })
  it('highlights the highest-priority point not yet used', () => {
    const o = (id: string, priority: number) => ({ id, priority }) as Overlay
    expect(topOpenPoint([o('a', 2), o('b', 5), o('c', 9)], new Set(['c']))).toBe('b')
    expect(topOpenPoint([o('a', 2)], new Set(['a']))).toBe(null)
  })
})

describe('desk strings (CD-17)', () => {
  it('every language has every desk string, non-empty', async () => {
    const { deskDictionaries } = await import('./deskText')
    const keys = Object.keys(deskDictionaries.en).sort()
    for (const [lang, dict] of Object.entries(deskDictionaries)) {
      expect(Object.keys(dict).sort(), lang).toEqual(keys)
      for (const [k, v] of Object.entries(dict)) expect(v.trim(), `${lang}.${k}`).not.toBe('')
    }
  })
})

describe('spotting-board names (CD-5)', () => {
  it('shortens long names to initial and surname', () => {
    expect(boardName('Callum Wolstenholme')).toBe('C. Wolstenholme')
    expect(boardName('Pablo Wakefield-Ames')).toBe('P. Wakefield-Ames')
    expect(boardName('Kai Greaves')).toBe('Kai Greaves')
    expect(boardName('Pelé')).toBe('Pelé')
  })
})

describe('context cards (CX-2, CX-5)', () => {
  it('keeps one card per moment and language, from hello and live messages', () => {
    const card = (moment_id: string, language: 'en' | 'es') => ({ moment_id, minute: '10', language, text: 't', entry_id: 'e',
      topic: 'T', kind: 'benchmark' as const, sources: [{ url: 'https://x.org', title: 'x' }], origin: 'web search' })
    const hello = { type: 'hello' as const, match_id: 'm', status: 'live' as const, speed: 1, audience: 'x', home: {} as never,
      away: {} as never, venue: '', referee: '', kickoff: '', weather: { condition: 'clear', temp_c: 10 }, score_home: 0,
      score_away: 0, context: [card('m1', 'en')] } satisfies Hello
    let s = reducer(initialState, hello)
    s = reducer(s, { type: 'context', context: card('m1', 'en') })
    s = reducer(s, { type: 'context', context: card('m2', 'en') })
    expect(s.contexts.map(c => c.moment_id)).toEqual(['m1', 'm2'])
  })
})

describe('followed player (F-5)', () => {
  it('a card is about the player if they are its main player or appear in its facts', async () => {
    const { involves } = await import('./scoreboard')
    const o = (player_id: string | null, data: Record<string, string | number | boolean> = {}) => ({ player_id, data }) as Overlay
    expect(involves(o('p9'), 'p9')).toBe(true)
    expect(involves(o(null, { assist: 'p9' }), 'p9')).toBe(true)
    expect(involves(o('p7', { scorer: 'p7' }), 'p9')).toBe(false)
    expect(involves(o('p9'), null)).toBe(false)
  })
})

describe('patterns (PA-6)', () => {
  it('alerted patterns become talking points once', () => {
    const note = (id: string) => ({ pattern_id: id, team_id: 'har', kind: 'flank' as const, scope: 'match' as const, value: 'left',
      text: 't', numbers: {}, source: 'plain' as const })
    const upd = (alerts: string[], minute: string) => ({ type: 'patterns' as const, minute, elapsed_ms: 1, language: 'en' as const,
      notes: [note('a'), note('b')], alerts, fan_lines: {} })
    let s = reducer(initialState, upd([], '10'))
    s = reducer(s, upd(['a'], '15'))
    s = reducer(s, upd(['a'], '20'))
    expect(s.patternAlerts.map(a => [a.pattern_id, a.minute])).toEqual([['a', '15']])
    expect(s.patterns?.minute).toBe('20')
  })
})

import { describe, expect, it } from 'vitest'
import { initialState, reducer, type State } from './state'
import type { Message, Overlay } from './types'

const club = (id: string) => ({
  id, name: id.toUpperCase(), short_name: id, colors: ['#111111', '#ffffff'] as [string, string],
  lineup: [{ id: `${id}-09`, name: `Striker ${id}`, number: 9, position: 'ST' }], bench: [],
})

const hello: Message = {
  type: 'hello', match_id: 'm1', status: 'waiting', speed: 30, audience: 'fan.en.-.-',
  home: club('har'), away: club('ngc'), venue: 'V', referee: 'R', kickoff: '15:00',
  weather: { condition: 'clear', temp_c: 10 }, score_home: 0, score_away: 0,
}

const overlay = (over: Partial<Overlay> = {}): Overlay => ({
  id: 'm1-mo0001:fan.en.-.-', match_id: 'm1', moment_id: 'm1-mo0001', audience: 'fan.en.-.-', kind: 'goal', team_id: 'har',
  priority: 0.95, slot: 'lower_third', clock_in_ms: 600_000, clock_out_ms: 612_000, minute: '11', elapsed_in_ms: 600_000,
  headline: 'GOAL!', body: 'Template body', language: 'en', direction: 'ltr', source: 'template', version: 1,
  evidence: ['f0'], data: { score_home: 1, score_away: 0 }, model: null, ...over,
})

const event = (over: Record<string, unknown> = {}): Message => ({
  type: 'event', kind: 'pass', seq: 1, period: 1, clock_ms: 61_000, display_minute: '2', team_id: 'har',
  player_id: 'har-09', player: 'Striker har', outcome: 'complete', score_home: 0, score_away: 0,
  x: 40, y: 30, end_x: 55, end_y: 20, ...over,
} as Message)

const run = (...msgs: Message[]): State => msgs.reduce(reducer, initialState)

describe('reducer', () => {
  it('hello sets clubs and resets match-specific state', () => {
    const s = run(hello)
    expect(s.hello?.home.name).toBe('HAR')
    expect(s.status).toBe('waiting')
    expect(s.feed).toEqual([])
  })

  it('events move the ball, keep a short trail, and update clock and score', () => {
    let s = run(hello)
    for (let i = 0; i < 30; i++) s = reducer(s, event({ seq: i, clock_ms: 1000 * i }))
    expect(s.ball).toEqual({ x: 55, y: 20 })
    expect(s.trail.length).toBeLessThanOrEqual(12)
    expect(s.minute).toBe('2')
    expect(s.status).toBe('live')
    s = reducer(s, event({ kind: 'goal', score_home: 1, x: null, y: null, end_x: null, end_y: null }))
    expect(s.score).toEqual([1, 0])
    expect(s.ball).toEqual({ x: 55, y: 20 }) // events without coordinates leave the ball alone
  })

  it('feed keeps one entry per overlay id and the newest version wins', () => {
    const s = run(
      hello,
      { type: 'overlay', overlay: overlay() },
      { type: 'overlay', overlay: overlay({ version: 2, source: 'ai', body: 'Why it matters' }) },
      { type: 'overlay', overlay: overlay({ version: 1, body: 'stale template' }) },
    )
    expect(s.feed).toHaveLength(1)
    expect(s.feed[0].body).toBe('Why it matters')
    expect(s.upgraded.has(overlay().id)).toBe(true)
  })

  it('feed is newest first and capped', () => {
    let s = run(hello)
    for (let i = 0; i < 120; i++) {
      s = reducer(s, { type: 'overlay', overlay: overlay({ id: `o${i}`, elapsed_in_ms: i * 1000 }) })
    }
    expect(s.feed[0].id).toBe('o119')
    expect(s.feed.length).toBeLessThanOrEqual(100)
  })

  it('backfill seeds the feed in chronological order without duplicates', () => {
    const s = run(hello, {
      type: 'backfill', overlays: [overlay({ id: 'a', elapsed_in_ms: 1 }), overlay({ id: 'b', elapsed_in_ms: 2 })],
    })
    expect(s.feed.map(o => o.id)).toEqual(['b', 'a'])
  })

  it('screen replaces what is on screen', () => {
    const s = run(hello, { type: 'screen', overlays: [overlay()] }, { type: 'screen', overlays: [] })
    expect(s.screen).toEqual([])
  })

  it('stats record a momentum point per minute', () => {
    const stats = (clock: number, m: number): Message => ({
      type: 'stats', clock_ms: clock, period: 1, chaos: 0.5,
      home: { window: { momentum: m } } as never, away: { window: { momentum: -m } } as never,
    })
    const s = run(hello, stats(60_000, 0.2), stats(60_500, 0.3), stats(120_000, -0.4))
    expect(s.momentum).toEqual([{ minute: 1, value: 0.3 }, { minute: 2, value: -0.4 }])
  })

  it('trace keeps recent events and counts outcomes', () => {
    const t = (outcome: string, agent = 'critic') => ({
      type: 'trace', trace: { moment_id: 'x', audience: '*', agent, outcome, model: null, ms: 5, detail: '' },
    }) as Message
    const s = run(hello, t('ok'), t('rejected'), t('published', 'validator'), t('stale', 'validator'))
    expect(s.trace[0].outcome).toBe('stale')
    expect(s.counts).toEqual({ published: 1, rejected: 1, stale: 1, error: 0 })
  })

  it('recaps are keyed by kind', () => {
    const recap = (kind: 'half_time' | 'full_time', headline: string): Message => ({
      type: 'recap', recap: { kind, headline, summary: '', key_points: [], language: 'en', model: null },
    })
    const s = run(hello, recap('half_time', 'HT'), recap('full_time', 'FT'), recap('half_time', 'HT2'))
    expect(s.recaps.half_time?.headline).toBe('HT2')
    expect(s.recaps.full_time?.headline).toBe('FT')
  })

  it('end finishes the match', () => {
    const s = run(hello, { type: 'end', score_home: 2, score_away: 1 })
    expect(s.status).toBe('finished')
    expect(s.score).toEqual([2, 1])
  })
})

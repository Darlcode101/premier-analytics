import { describe, expect, it } from 'vitest'
import { explainAttack, linkedMoments } from './explain'
import type { AttackPoint, Overlay } from './types'

const point = (value: number, home: Partial<AttackPoint['home']>, away: Partial<AttackPoint['away']> = {}): AttackPoint => ({
  minute: 33, value, window: [31, 33], label: '34',
  home: { shots: 0, xg: 0, final_third_passes: 0, high_regains: 0, ...home },
  away: { shots: 0, xg: 0, final_third_passes: 0, high_regains: 0, ...away },
})
const names = { har: 'Harbourside', ngc: 'Northgate' }

describe('explainAttack', () => {
  it('names the team on top and the reasons, with the real numbers', () => {
    const e = explainAttack(point(0.6, { shots: 2, xg: 0.38, final_third_passes: 7, high_regains: 3 }), 'har', 'ngc', names, 'en')
    expect(e.leader).toBe('har')
    expect(e.headline).toBe('Harbourside on top')
    expect(e.reasons).toEqual(['2 shots (0.38 xG)', '7 passes into the final third', 'won the ball 3 times in the opponent\'s half'])
  })

  it('points to the away side when the bar is negative', () => {
    const e = explainAttack(point(-0.4, {}, { final_third_passes: 4 }), 'har', 'ngc', names, 'en')
    expect(e.leader).toBe('ngc')
    expect(e.reasons).toEqual(['4 passes into the final third'])
  })

  it('calls small bars even, and quiet ones quiet', () => {
    expect(explainAttack(point(0.05, { final_third_passes: 1 }, { final_third_passes: 1 }), 'har', 'ngc', names, 'en').headline).toBe('Evenly balanced')
    expect(explainAttack(point(0, {}), 'har', 'ngc', names, 'en').reasons).toEqual([])
  })

  it('uses singular forms and works in every language', () => {
    expect(explainAttack(point(0.5, { shots: 1, xg: 0.1 }), 'har', 'ngc', names, 'en').reasons).toEqual(['1 shot (0.1 xG)'])
    expect(explainAttack(point(0.5, { shots: 2, xg: 0.3 }), 'har', 'ngc', names, 'es').headline).toBe('Harbourside domina')
    expect(explainAttack(point(0.5, { shots: 2, xg: 0.3 }), 'har', 'ngc', names, 'ar').reasons[0]).toContain('2')
  })
})

describe('linkedMoments', () => {
  const ov = (kind: string, minute: number): Overlay => ({ kind, elapsed_in_ms: minute * 60_000, id: `${kind}${minute}` } as Overlay)
  it('finds momentum and pressure moments inside the bar\'s window', () => {
    const feed = [ov('momentum_shift', 32), ov('pressure_spell', 20), ov('goal', 33), ov('pressure_spell', 34)]
    expect(linkedMoments(feed, point(0.5, {})).map(o => o.id)).toEqual(['momentum_shift32', 'pressure_spell34'])
  })
})

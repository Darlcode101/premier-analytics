import { describe, expect, it } from 'vitest'
import { groupKey, latestGroup, subGroups } from './subs'
import type { Incident } from './types'

const sub = (id: string, elapsed_ms: number, extra: Partial<Incident> = {}): Incident => ({
  id, event_id: id, kind: 'sub', minute: String(Math.floor(elapsed_ms / 60_000) + 1), elapsed_ms, period: 2,
  team_id: 'har', player_id: `${id}-in`, player_in_id: `${id}-in`, player_out_id: `${id}-out`, ...extra,
})
const goal: Incident = { id: 'g', event_id: 'g', kind: 'goal', minute: '61', elapsed_ms: 3_650_000, period: 2, team_id: 'har', player_id: 'p9' }

describe('substitution cards (SB-3)', () => {
  it('changes at the same stoppage share one card, a later change starts a new one', () => {
    const incs = [sub('a', 3_600_000), sub('b', 3_625_000, { team_id: 'ngc' }), goal, sub('c', 3_660_000), sub('d', 4_500_000)]
    expect(subGroups(incs).map(g => g.map(i => i.id))).toEqual([['a', 'b', 'c'], ['d']])
  })
  it('ignores incident order and other incidents', () => {
    const incs = [sub('d', 4_500_000), goal, sub('a', 3_600_000)]
    expect(subGroups(incs).map(g => g.map(i => i.id))).toEqual([['a'], ['d']])
    expect(latestGroup(incs)?.map(i => i.id)).toEqual(['d'])
    expect(latestGroup([goal])).toBeNull()
  })
  it('a timeline entry finds its card', () => {
    const incs = [sub('a', 3_600_000), sub('b', 3_620_000)]
    expect(groupKey(subGroups(incs), 'b')).toBe('a')
    expect(groupKey(subGroups(incs), 'zzz')).toBeNull()
  })
})

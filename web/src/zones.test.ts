import { describe, expect, it } from 'vitest'
import { attacksRight, cellOf, describeZone } from './zones'

describe('zones', () => {
  it('every point on the pitch maps to exactly one of 9 cells', () => {
    const seen = new Set<string>()
    for (let x = 0; x <= 105; x += 2.5) {
      for (let y = 0; y <= 68; y += 2) {
        const c = cellOf(x, y)
        expect(c.col).toBeGreaterThanOrEqual(0)
        expect(c.col).toBeLessThanOrEqual(2)
        expect(c.row).toBeGreaterThanOrEqual(0)
        expect(c.row).toBeLessThanOrEqual(2)
        seen.add(`${c.col},${c.row}`)
      }
    }
    expect(seen.size).toBe(9)
  })

  it('home attacks right in the first half and left in the second', () => {
    expect(attacksRight('home', 1, 'home')).toBe(true)
    expect(attacksRight('home', 2, 'home')).toBe(false)
    expect(attacksRight('away', 1, 'home')).toBe(false)
    expect(attacksRight('away', 2, 'home')).toBe(true)
  })

  it('describes the zone from the attacking team\'s point of view', () => {
    // near the right-hand goal, top touchline: final third, on the left for a team attacking right
    expect(describeZone(95, 5, true)).toEqual({ third: 'final', channel: 'left' })
    // same spot for the team attacking left: it's their defensive third, on their right
    expect(describeZone(95, 5, false)).toEqual({ third: 'defensive', channel: 'right' })
    expect(describeZone(52.5, 34, true)).toEqual({ third: 'middle', channel: 'centre' })
  })
})

import { describe, expect, it } from 'vitest'
import { scoreboardSides } from './scoreboard'

const home = { id: 'har' } as never
const away = { id: 'ngc' } as never

describe('scoreboard pinning', () => {
  it('home on the left when no favourite is chosen', () => {
    const s = scoreboardSides(home, away, [2, 1], null)
    expect([s.left.club, s.right.club]).toEqual([home, away])
    expect([s.left.goals, s.right.goals]).toEqual([2, 1])
    expect(s.pinned).toBe(false)
  })

  it('favourite club pinned on the left with its goals first', () => {
    const s = scoreboardSides(home, away, [2, 1], 'ngc')
    expect([s.left.club, s.right.club]).toEqual([away, home])
    expect([s.left.goals, s.right.goals]).toEqual([1, 2])
    expect(s.pinned).toBe(true)
  })

  it('favouring the home side keeps the normal order but marks it', () => {
    const s = scoreboardSides(home, away, [0, 3], 'har')
    expect([s.left.club, s.right.club]).toEqual([home, away])
    expect(s.pinned).toBe(true)
  })
})
